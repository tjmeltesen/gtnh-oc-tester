"""Specification ingestion and Schema Registry for GTNH 2.9 OpenComputers."""

from .dump_parser import (
    DumpMethodSpec,
    DumpOverloadSpec,
    DumpParamSpec,
    DumpSpec,
    load_all_dumps,
    parse_doc_signature,
    parse_dump_file,
)
from .jar_loader import DEFAULT_JAR_VERSION, DEFAULT_OC_JAR_URL, OCJarLoader, SUPPORTED_JAR_VERSIONS
from .oc_config import OCMachineConfig, load_oc_config
from .registry import (
    DEFAULT_VALIDATED_SIMULATOR_TYPES,
    ResolvedComponentSchema,
    SchemaRegistry,
    get_default_registry,
    validate_simulator_dumps,
)
from .stub_parser import (
    StubClassSpec,
    StubFieldSpec,
    StubMethodSpec,
    StubOverloadSpec,
    StubParamSpec,
    StubReturnSpec,
    load_all_stubs,
    parse_stub_file,
)

__all__ = [
    "DEFAULT_JAR_VERSION",
    "DEFAULT_OC_JAR_URL",
    "DEFAULT_VALIDATED_SIMULATOR_TYPES",
    "DumpMethodSpec",
    "DumpOverloadSpec",
    "DumpParamSpec",
    "DumpSpec",
    "OCJarLoader",
    "OCMachineConfig",
    "ResolvedComponentSchema",
    "SUPPORTED_JAR_VERSIONS",
    "SchemaRegistry",
    "StubClassSpec",
    "StubFieldSpec",
    "StubMethodSpec",
    "StubOverloadSpec",
    "StubParamSpec",
    "StubReturnSpec",
    "get_default_registry",
    "load_all_dumps",
    "load_all_stubs",
    "load_oc_config",
    "parse_doc_signature",
    "parse_dump_file",
    "parse_stub_file",
    "validate_simulator_dumps",
]
