"""OpenAPI Tool."""

import json
import logging
from collections import OrderedDict
from typing import List, Optional, Callable

import requests
from llama_index.core.schema import Document
from llama_index.core.tools.tool_spec.base import BaseToolSpec

logger = logging.getLogger(__name__)


class OpenAPIToolSpec(BaseToolSpec):
    """
    OpenAPI Tool.

    This tool can be used to parse an OpenAPI spec for endpoints and operations
    Use the RequestsToolSpec to automate requests to the openapi server
    """

    spec_functions = ["load_openapi_spec"]

    def __init__(
        self,
        spec: Optional[dict] = None,
        url: Optional[str] = None,
        operation_id_filter: Callable[[str], bool] = None,
        inline_schema_refs: bool = True,
        max_inlined_cycle_depth: int = 1,
        max_inlined_schema_nest_depth: int = 20,
    ):
        """
        Constructs an instance based on either a spec or a url to a spec.

        Args:
            spec: a spec already parsed into a dict
            url: a url from which to retrieve the spec
            operation_id_filter: an optional predicate for filtering specific operation ids
            inline_schema_refs: set false to disable inlining of $ref, which can reduce the size
              of the resulting document and avoid problems due to cyclical references
            max_inlined_cycle_depth: if inlining enabled, controls how many times a ref can be
              inlined within its own tree
            max_inlined_schema_nest_depth: if inlining enabled, prevents cycles of $ref from causing
              infinite loops or stack overflows

        """
        import yaml

        if spec and url:
            raise ValueError("Only provide one of OpenAPI dict or url")
        elif spec:
            pass
        elif url:
            response = requests.get(url).text
            spec = yaml.safe_load(response)
        else:
            raise ValueError("You must provide a url or OpenAPI spec as a dict")

        self.inline_schema_refs = inline_schema_refs
        self.max_inlined_cycle_depth = max_inlined_cycle_depth
        self.max_inlined_schema_nest_depth = max_inlined_schema_nest_depth

        # TODO: if we retrieved spec from URL, the server URL inside the spec may be relative to
        #  the retrieval URL.
        parsed_spec = self.process_api_spec(spec, operation_id_filter)
        self.spec = Document(text=json.dumps(parsed_spec))

    def load_openapi_spec(self) -> List[Document]:
        """
        You are an AI agent specifically designed to retrieve information by making web requests to
        an API based on an OpenAPI specification.

        Here's a step-by-step guide to assist you in answering questions:

        1. Determine the server base URL required for making the request

        2. Identify the relevant endpoint (a HTTP verb plus path template) necessary to address the
        question

        3. Generate the required parameters and/or request body for making the request to the
        endpoint

        4. Perform the necessary requests to obtain the answer

        Returns:
            Document: A List of Document objects that describes the available API.

        """
        return [self.spec]

    def process_api_spec(
        self, spec: dict, operation_id_filter: Callable[[str], bool]
    ) -> dict:
        """
        Perform simplification and reduction on an OpenAPI specification.

        The goal is to create a more concise and efficient representation
        for retrieval purposes.
        """

        def reduce_details(details: dict) -> dict:
            reduced = OrderedDict()
            if details.get("description"):
                reduced["description"] = details.get("description")
            elif details.get("summary"):
                reduced["description"] = details.get("summary")
            if details.get("parameters"):
                reduced["parameters"] = details.get("parameters", [])
            if details.get("requestBody"):
                reduced["requestBody"] = details.get("requestBody")
            if "200" in details["responses"]:
                reduced["responses"] = details["responses"]["200"]
            return reduced

        preserve_refs = set()
        def inline_refs(openapi_doc):
            """Inlines all $ref pointers in a Swagger/OpenAPI document."""
            try:
                import jsonschema
            except ImportError:
                raise ImportError(
                    "The jsonschema library is required to parse OpenAPI documents. "
                    "Please install it with `pip install jsonschema`."
                )

            resolver = jsonschema.RefResolver.from_schema(openapi_doc)
            ref_stack = []
            def _dereference(obj):
                ref_depth = len(ref_stack)
                if ref_depth > self.max_inlined_schema_nest_depth:
                    raise RuntimeError(f"Reached maximum depth of nested $ref. "
                                       f"Ref stack; {ref_stack}")
                if isinstance(obj, dict):
                    if "$ref" in obj:
                        ref = obj["$ref"]
                        if ref_stack.count(ref) >= self.max_inlined_cycle_depth:
                            logger.debug("Reached max cyclical nesting of %s. "
                                         "Ref stack: %s", ref, ref_stack)
                            return obj
                        ref_stack.append(ref)
                        if ref.startswith("#/components/schemas/"):
                            schema_name = ref.split("/")[-1]
                            preserve_refs.add(schema_name)
                        try:
                            with resolver.resolving(ref) as resolved:
                                inlined = _dereference(resolved)
                        finally:
                            ref_stack.pop()
                        return inlined
                    return {k: _dereference(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_dereference(item) for item in obj]
                return obj

            paths = _dereference(openapi_doc["paths"])
            openapi_doc["paths"] = paths
            return openapi_doc

        if self.inline_schema_refs:
            spec = inline_refs(spec)

        endpoints = []
        for path_template, operations in spec["paths"].items():
            for operation, operation_detail in operations.items():
                operation_id = operation_detail.get("operationId")
                if operation_id_filter is None or operation_id_filter(operation_id):
                    if operation in ["get", "post", "patch", "put", "delete"]:
                        # preserve order so the LLM "reads" the description first before all the
                        # schema details
                        details = OrderedDict()
                        details["verb"] = operation.upper()
                        details["path_template"] = path_template
                        details.update(reduce_details(operation_detail))
                        endpoints.append(details)

        result = {
            "description": spec["info"].get("description"),
            "endpoints": endpoints,
        }
        if "servers" in spec:
            result["servers"] = spec["servers"]
        if not self.inline_schema_refs:
            # Some of these may be unreferenced/unnecessary.
            result["components"] = spec["components"]
        else:
            result["components"] = {
                "schemas": {
                    name: spec["components"]["schemas"][name]
                    for name in preserve_refs
                }
            }

        return result
