import json
from pathlib import Path

import pytest
import yaml

from llama_index.core.tools.tool_spec.base import BaseToolSpec
from llama_index.tools.openapi import OpenAPIToolSpec


def test_class():
    names_of_base_classes = [b.__name__ for b in OpenAPIToolSpec.__mro__]
    assert BaseToolSpec.__name__ in names_of_base_classes


def test_opid_filter():
    openapi_spec = load_example_spec()
    llamaindex_tool_spec = OpenAPIToolSpec(
        spec=openapi_spec, operation_id_filter=lambda it: it != "findPetsByTags"
    )
    spec_array = llamaindex_tool_spec.load_openapi_spec()
    deserialized = json.loads(spec_array[0].text)
    endpoints: list = deserialized["endpoints"]
    operation = next(
        filter(lambda it: it["path_template"] == "/pet/findByTags", endpoints), None
    )
    assert operation is None


def test_request_body():
    openapi_spec = load_example_spec()
    llamaindex_tool_spec = OpenAPIToolSpec(spec=openapi_spec)
    spec_array = llamaindex_tool_spec.load_openapi_spec()
    deserialized = json.loads(spec_array[0].text)
    endpoints: list = deserialized["endpoints"]
    operation = next(
        filter(
            lambda it: it["path_template"] == "/pet" and it["verb"] == "PUT", endpoints
        )
    )
    assert isinstance(operation["requestBody"], dict)


def load_example_spec(name="example.json"):
    current_file_path = Path(__file__).resolve()
    example_file = current_file_path.parent / name
    with example_file.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def test_no_inlining():
    openapi_spec = load_example_spec("cyclical.json")
    llamaindex_tool_spec = OpenAPIToolSpec(spec=openapi_spec, inline_schema_refs=False)
    spec_array = llamaindex_tool_spec.load_openapi_spec()
    deserialized = json.loads(spec_array[0].text)

    # Assert that the deserialized output contains endpoints
    assert "endpoints" in deserialized
    assert isinstance(deserialized["endpoints"], list)

    # Assert that schemas are not inlined and $ref keys are present
    components = deserialized.get("components", {})
    schemas = components.get("schemas", {})
    assert "SelfReferencingObject" in schemas
    assert "TickObject" in schemas
    assert "TockObject" in schemas
    assert "$ref" in schemas["SelfReferencingObject"]["properties"]["child"]
    assert "$ref" in schemas["TickObject"]["properties"]["tock"]
    assert "$ref" in schemas["TockObject"]["properties"]["tick"]


def test_one_cycle_depth():
    openapi_spec = load_example_spec("cyclical.json")
    llamaindex_tool_spec = OpenAPIToolSpec(spec=openapi_spec, max_inlined_cycle_depth=1)
    spec_array = llamaindex_tool_spec.load_openapi_spec()
    deserialized = json.loads(spec_array[0].text)

    # Assert that schemas are partially inlined under endpoints
    endpoints = deserialized["endpoints"]
    selfref_path = next(
        endpoint for endpoint in endpoints if endpoint["path_template"] == "/self-reference"
    )
    tick_tock_path = next(
        endpoint for endpoint in endpoints if endpoint["path_template"] == "/tick-tock"
    )

    # SelfReferencingObject should inline its child once, but the child's child should remain a $ref
    self_ref = selfref_path["responses"]["content"].get("application/json", {})["schema"]
    assert "properties" in self_ref
    assert "child" in self_ref["properties"]
    assert "$ref" in self_ref["properties"]["child"]
    assert self_ref["properties"]["child"]["$ref"] == "#/components/schemas/SelfReferencingObject"

    # TickObject should inline TockObject once, but TockObject's tick should remain a $ref
    tick = tick_tock_path["responses"]["content"]["application/json"]["schema"]
    assert "properties" in tick
    assert "tock" in tick["properties"]
    assert "properties" in tick["properties"]["tock"]
    assert "$ref" in tick["properties"]["tock"]["properties"]["tick"]

    # Assert that components remain as $ref in the components section
    schemas = deserialized["components"]["schemas"]
    assert "SelfReferencingObject" in schemas
    assert "TickObject" in schemas
    assert "TockObject" in schemas
    assert "$ref" in schemas["SelfReferencingObject"]["properties"]["child"]
    assert "$ref" in schemas["TickObject"]["properties"]["tock"]
    assert "$ref" in schemas["TockObject"]["properties"]["tick"]


def test_max_nest_depth():
    openapi_spec = load_example_spec("cyclical.json")

    with pytest.raises(RuntimeError, match=r"Reached maximum depth of nested \$ref\."):
        llamaindex_tool_spec = OpenAPIToolSpec(spec=openapi_spec,
                                           max_inlined_cycle_depth=10,
                                           max_inlined_schema_nest_depth=3)
