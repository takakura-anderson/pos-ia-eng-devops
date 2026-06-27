"""
Job de descoberta de dados disponíveis na Receita Federal.

Faz uso da API WebDAV do Nextcloud (SERPRO+) para listar:
1. Pastas disponíveis no formato YYYY-MM
2. Arquivos .zip dentro de cada pasta

Registra tudo na tabela sync_control com status 'pending'.

URL base: https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9
"""

import logging
import re
import xml.etree.ElementTree as ET

import requests
from sqlalchemy.orm import Session

from src.config import RECEITA_BASE_URL
from src.exceptions import DataDiscoveryError
from src.models.sync_control import SyncControl
from src.models.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Extrai o token de compartilhamento da URL base
# Ex: https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9 -> YggdBLfdninEJX9
SHARE_TOKEN = RECEITA_BASE_URL.rstrip("/").split("/")[-1]
WEBDAV_BASE_URL = "https://arquivos.receitafederal.gov.br/public.php/webdav"


def _list_webdav(path: str = "/") -> list[dict]:
    """
    Lista o conteúdo de um diretório no Nextcloud usando a API WebDAV.
    Retorna uma lista de dicionários com 'name', 'is_dir' e 'size'.
    """
    url = f"{WEBDAV_BASE_URL}{path}"
    headers = {"Depth": "1"}
    auth = (SHARE_TOKEN, "")

    logger.info(f"Executando PROPFIND na URL WebDAV: {url}")

    response = requests.request("PROPFIND", url, headers=headers, auth=auth, timeout=30)

    if response.status_code not in (200, 207):
        logger.error(f"Erro WebDAV: Status {response.status_code}\n{response.text[:500]}")
        raise DataDiscoveryError(
            f"Falha ao consultar WebDAV em {url}. HTTP {response.status_code}."
        )

    # Parseia a resposta XML do WebDAV
    items = []
    try:
        root = ET.fromstring(response.content)
        # Namespaces XML utilizados pelo WebDAV do Nextcloud
        ns = {"d": "DAV:", "oc": "http://owncloud.org/ns", "nc": "http://nextcloud.org/ns"}

        for response_elem in root.findall("d:response", ns):
            href = response_elem.find("d:href", ns)
            if href is None:
                continue

            href_text = href.text.rstrip("/")
            if not href_text:
                continue

            # O nome do item é o último componente do caminho
            name = href_text.split("/")[-1]

            # Ignora o diretório atual (".")
            if url.rstrip("/").endswith(href_text) or path.rstrip("/") == href_text:
                continue

            propstat = response_elem.find("d:propstat/d:prop", ns)
            if propstat is None:
                continue

            resourcetype = propstat.find("d:resourcetype", ns)
            is_dir = resourcetype is not None and resourcetype.find("d:collection", ns) is not None

            size_elem = propstat.find("d:getcontentlength", ns)
            size = int(size_elem.text) if size_elem is not None and size_elem.text else None

            etag_elem = propstat.find("d:getetag", ns)
            etag = etag_elem.text if etag_elem is not None else None

            items.append(
                {
                    "name": name,
                    "is_dir": is_dir,
                    "size": size,
                    "etag": etag,
                }
            )

    except ET.ParseError as e:
        logger.error(f"Erro ao parsear XML WebDAV: {e}\n{response.text[:500]}")
        raise DataDiscoveryError(f"Resposta inválida do WebDAV em {url}: {e}")

    return items


def _list_folders() -> list[str]:
    """Lista as pastas YYYY-MM disponíveis."""
    items = _list_webdav("/")
    pattern = re.compile(r"^\d{4}-\d{2}$")

    folders = [item["name"] for item in items if item["is_dir"] and pattern.match(item["name"])]
    folders = sorted(set(folders))

    if not folders:
        raise DataDiscoveryError(
            "Nenhuma pasta YYYY-MM encontrada na raiz do WebDAV. Verifique a URL ou o token."
        )

    logger.info(f"Encontradas {len(folders)} pastas: {folders}")
    return folders


def _list_files_in_folder(folder: str) -> list[dict]:
    """Lista os arquivos .zip dentro de uma pasta YYYY-MM."""
    items = _list_webdav(f"/{folder}/")
    zip_pattern = re.compile(r".*\.zip$", re.IGNORECASE)

    files = []
    for item in items:
        if not item["is_dir"] and zip_pattern.match(item["name"]):
            files.append(
                {
                    "file_name": item["name"],
                    "file_size_bytes": item["size"],
                    "etag": item.get("etag"),
                }
            )

    if not files:
        raise DataDiscoveryError(f"Nenhum arquivo .zip encontrado na pasta {folder}.")

    logger.info(f"Encontrados {len(files)} arquivos em {folder}")
    return files


def discover_available_data(db: Session) -> dict:
    """
    Processo principal de descoberta.
    1. Lista pastas YYYY-MM disponíveis e arquivos avulsos na raiz
    2. Para cada pasta, lista arquivos .zip
    3. Registra na tabela sync_control (se ainda não existir)
    """
    logger.info("=== Iniciando Discovery de Dados da Receita Federal ===")

    new_months = 0
    new_files = 0

    # Pega os arquivos da raiz (.tar.gz ou .zip)
    root_items = _list_webdav("/")
    for item in root_items:
        if not item["is_dir"] and (
            item["name"].lower().endswith(".zip") or item["name"].lower().endswith(".tar.gz")
        ):
            existing = (
                db.query(SyncControl)
                .filter(SyncControl.year_month == "BASE", SyncControl.file_name == item["name"])
                .count()
            )
            if existing == 0:
                sync_record = SyncControl(
                    year_month="BASE",
                    file_name=item["name"],
                    file_size_bytes=item["size"],
                    etag=item.get("etag"),
                    status="pending",
                )
                db.add(sync_record)
                new_files += 1
                db.commit()
                logger.info(f"Arquivo base na raiz registrado: {item['name']}")

    folders = _list_folders()

    for folder in folders:
        existing = db.query(SyncControl).filter(SyncControl.year_month == folder).count()

        if existing > 0:
            logger.info(f"Mês {folder} já descoberto ({existing} arquivos). Pulando.")
            continue

        new_months += 1
        files = _list_files_in_folder(folder)

        for file_info in files:
            sync_record = SyncControl(
                year_month=folder,
                file_name=file_info["file_name"],
                file_size_bytes=file_info["file_size_bytes"],
                etag=file_info.get("etag"),
                status="pending",
            )
            db.add(sync_record)
            new_files += 1

        db.commit()
        logger.info(f"Mês {folder}: {len(files)} arquivos registrados.")

    logger.info(
        f"=== Discovery finalizado: {new_months} novos meses, {new_files} novos arquivos ==="
    )

    return {"new_months": new_months, "new_files": new_files}


if __name__ == "__main__":
    from src.models.database import init_db

    init_db()
    db = SessionLocal()
    try:
        result = discover_available_data(db)
        logger.info(f"Resultado: {result}")
    finally:
        db.close()
