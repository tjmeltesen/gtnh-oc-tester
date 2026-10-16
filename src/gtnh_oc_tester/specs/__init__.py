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
from .jar_loader import DEFAULT_OC_JAR_URL, OCJarLoader
from .registry import ResolvedComponentSchema, SchemaRegistry, get_default_registry
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
    "DEFAULT_OC_JAR_URL",
    "DumpMethodSpec",
    "DumpOverloadSpec",
    "DumpParamSpec",
    "DumpSpec",
    "OCJarLoader",
    "ResolvedComponentSchema",
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
    "parse_doc_signature",
    "parse_dump_file",
    "parse_stub_file",
]
