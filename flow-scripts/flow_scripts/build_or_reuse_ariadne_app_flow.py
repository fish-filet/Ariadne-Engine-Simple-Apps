import json
import os
import re
from pathlib import Path
from typing import Literal

from aaa_types.consts import get_background_process_model_name
from aaa_types.dtos import (
    AriadneAppLtmDataspaceConfigDTO,
    AriadneAppConfigDTO,
    AriadneAppDiscoveryResponseDTO,
    AriadneAppLaunchResultDTO,
    ContextCreateDTO,
    GeneralConversationChatRequest,
    LtmDataspaceCreateDTO,
)
from flow_kit.engine_utils import EngineUtils, identity_key_var
from flow_kit.registry import flow

SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]")
APP_CONFIG_FILENAME = "ariadne_apps.json"
APP_INDEX_FILENAME = ".ariadne_app_context_index.json"


def _sanitize_identity(identity_key: str) -> str:
    sanitized_identity = SAFE_NAME_RE.sub("", identity_key)
    if sanitized_identity == "":
        raise ValueError("Identity key resolved to an empty storage directory name")
    return sanitized_identity


def _get_storage_base_dir() -> Path:
    storage_base_dir = os.environ.get("AAA_STORAGE_BASE_DIR")
    if storage_base_dir is None:
        raise ValueError("No AAA_STORAGE_BASE_DIR given by environment variable")
    storage_path = Path(storage_base_dir)
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


def _get_app_config_path() -> Path:
    return Path(__file__).with_name(APP_CONFIG_FILENAME)


def _get_identity_index_path(identity_key: str) -> Path:
    identity_dir = _get_storage_base_dir() / _sanitize_identity(identity_key) / "ariadne_apps"
    identity_dir.mkdir(parents=True, exist_ok=True)
    return identity_dir / APP_INDEX_FILENAME


def _load_app_configs() -> list[AriadneAppConfigDTO]:
    config_path = _get_app_config_path()
    if not config_path.exists():
        return []

    with config_path.open("r", encoding="utf-8") as file_handle:
        raw_data = json.load(file_handle)

    if not isinstance(raw_data, list):
        raise ValueError("Ariadne app config file must contain a JSON array")

    return [AriadneAppConfigDTO.model_validate(entry) for entry in raw_data]


def _load_app_index(index_path: Path) -> dict[str, str]:
    if not index_path.exists():
        return {}

    with index_path.open("r", encoding="utf-8") as file_handle:
        raw_data = json.load(file_handle)

    if not isinstance(raw_data, dict):
        return {}

    normalized_index: dict[str, str] = {}
    for app_id, context_uuid in raw_data.items():
        if not isinstance(app_id, str) or app_id == "":
            continue
        if not isinstance(context_uuid, str) or context_uuid == "":
            continue
        normalized_index[app_id] = context_uuid
    return normalized_index


def _save_app_index(index_path: Path, app_index: dict[str, str]) -> None:
    with index_path.open("w", encoding="utf-8") as file_handle:
        json.dump(app_index, file_handle, indent=2, sort_keys=True)


def _resolve_app_config(
    app_configs: list[AriadneAppConfigDTO], app_id: str
) -> AriadneAppConfigDTO:
    for app_config in app_configs:
        if app_config.app_id == app_id:
            return app_config
    raise ValueError(f"Unknown Ariadne app id: {app_id}")


def _build_context_name_candidate(base_name: str, attempt: int) -> str:
    if attempt <= 1:
        return base_name
    return f"{base_name} {attempt}"


def _normalize_app_ltm_dataspace_configs(
    app_config: AriadneAppConfigDTO,
) -> list[AriadneAppLtmDataspaceConfigDTO]:
    normalized_configs: dict[str, AriadneAppLtmDataspaceConfigDTO] = {}

    for dataspace_name in app_config.linked_ltm_dataspaces:
        normalized_name = dataspace_name.strip()
        if normalized_name == "":
            continue
        normalized_configs[normalized_name] = AriadneAppLtmDataspaceConfigDTO(
            name=normalized_name
        )

    for dataspace_config in app_config.ltm_dataspace_configs:
        normalized_name = dataspace_config.name.strip()
        if normalized_name == "":
            continue
        normalized_configs[normalized_name] = dataspace_config.model_copy(
            update={"name": normalized_name}
        )

    return list(normalized_configs.values())


def _resolve_dataspace_ingestion_model_name(
    dataspace_config: AriadneAppLtmDataspaceConfigDTO,
) -> str:
    configured_model_name = (dataspace_config.ingestion_model_name or "").strip()
    if configured_model_name != "":
        return configured_model_name
    return get_background_process_model_name()


async def _ensure_app_ltm_dataspace_exists(
    app_config: AriadneAppConfigDTO,
    dataspace_config: AriadneAppLtmDataspaceConfigDTO,
    engine_utils: EngineUtils,
) -> None:
    existing_dataspace = await engine_utils.get_ltm_dataspace_by_name(
        dataspace_config.name
    )
    if existing_dataspace is not None:
        return

    await engine_utils.create_ltm_dataspace(
        LtmDataspaceCreateDTO(name=dataspace_config.name)
    )

    initial_content = (dataspace_config.initial_content or "").strip()
    if initial_content == "":
        return

    await engine_utils.ingest_data_into_ltm_graph(
        text=initial_content,
        dataspace_name=dataspace_config.name,
        model=_resolve_dataspace_ingestion_model_name(dataspace_config),
        episode_name=dataspace_config.episode_name,
        source_description=dataspace_config.source_description
        or f"Ariadne app dataspace bootstrap for {app_config.ui_name}",
    )


async def _ensure_app_ltm_dataspaces_are_ready(
    app_config: AriadneAppConfigDTO,
    context_key: str,
    engine_utils: EngineUtils,
) -> None:
    for dataspace_config in _normalize_app_ltm_dataspace_configs(app_config):
        await _ensure_app_ltm_dataspace_exists(
            app_config=app_config,
            dataspace_config=dataspace_config,
            engine_utils=engine_utils,
        )
        await engine_utils.add_ltm_dataspace_to_context(
            context_key, dataspace_config.name
        )


async def _build_unique_context_name(
    app_config: AriadneAppConfigDTO, engine_utils: EngineUtils
) -> str:
    base_name = app_config.ui_name.strip()
    if base_name == "":
        raise ValueError(f"App '{app_config.app_id}' has an empty ui_name")

    attempt = 1
    while True:
        candidate = _build_context_name_candidate(base_name, attempt)
        existing_context = await engine_utils.get_context_by_name(candidate)
        if existing_context is None:
            return candidate
        attempt += 1


async def _create_app_context(
    app_config: AriadneAppConfigDTO,
    engine_utils: EngineUtils,
) -> str:
    context_name = await _build_unique_context_name(app_config, engine_utils)
    created_context = await engine_utils.create_context(
        ContextCreateDTO(
            context_name=context_name,
            description=app_config.context_description,
            context_model_name=app_config.context_model_name,
            use_short_term_memory=app_config.use_short_term_memory,
            allow_external_tools=app_config.allow_external_tools,
            allow_master_tool=app_config.allow_master_tool,
        )
    )

    for skill_name in app_config.linked_skills:
        await engine_utils.add_skill_to_context(created_context.key, skill_name)

    await _ensure_app_ltm_dataspaces_are_ready(
        app_config=app_config,
        context_key=created_context.key,
        engine_utils=engine_utils,
    )

    return created_context.key


async def _build_or_reuse_app_context(
    app_config: AriadneAppConfigDTO,
    engine_utils: EngineUtils,
    identity_key: str,
) -> AriadneAppLaunchResultDTO:
    index_path = _get_identity_index_path(identity_key)
    app_index = _load_app_index(index_path)
    indexed_context_uuid = app_index.get(app_config.app_id)

    if indexed_context_uuid is not None:
        existing_context = await engine_utils.get_context_by_key(indexed_context_uuid)
        if existing_context is not None:
            await _ensure_app_ltm_dataspaces_are_ready(
                app_config=app_config,
                context_key=existing_context.key,
                engine_utils=engine_utils,
            )
            return AriadneAppLaunchResultDTO(
                context_uuid=existing_context.key,
                initial_prompt=app_config.initial_prompt,
                app_id=app_config.app_id,
                ui_name=app_config.ui_name,
                metadata=app_config.metadata,
            )
        app_index.pop(app_config.app_id, None)
        _save_app_index(index_path, app_index)

    created_context_uuid = await _create_app_context(app_config, engine_utils)
    app_index[app_config.app_id] = created_context_uuid
    _save_app_index(index_path, app_index)

    return AriadneAppLaunchResultDTO(
        context_uuid=created_context_uuid,
        initial_prompt=app_config.initial_prompt,
        app_id=app_config.app_id,
        ui_name=app_config.ui_name,
        metadata=app_config.metadata,
    )


@flow(is_agentic_flow=False)
async def build_or_reuse_ariadne_app_flow(
    dto: GeneralConversationChatRequest,
    mode: Literal["discover", "create_or_reuse"] = "discover",
    app_id: str = "",
):
    """
    Discover Ariadne app configurations or create/reuse the app context for one app.

    Args:
        mode: `discover` returns all available app configurations. `create_or_reuse` returns a context UUID and initial prompt for one app.
        app_id: Required when `mode` is `create_or_reuse`.
    """
    identity_key = identity_key_var.get()
    engine_utils = EngineUtils(identity_key)
    app_configs = _load_app_configs()

    if mode == "discover":
        return AriadneAppDiscoveryResponseDTO(apps=app_configs).model_dump(mode="json")

    if app_id.strip() == "":
        raise ValueError("The app_id parameter is required in create_or_reuse mode")

    app_config = _resolve_app_config(app_configs, app_id.strip())
    launch_result = await _build_or_reuse_app_context(
        app_config=app_config,
        engine_utils=engine_utils,
        identity_key=identity_key,
    )
    return launch_result.model_dump(mode="json")
