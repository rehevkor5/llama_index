# CHANGELOG

## [0.5.0]

- Allow schema inlining to be disabled, which can reduce the size of the resulting document and
  avoid problems due to cyclical references
- Add control over how many times an object can be inlined within its own subtree. This allows for
  some inlining but falls back on $ref for cyclical things.
- Add control over max inlined nesting depth, to prevent infinite loops or stack overflows when
  nesting is very deep, even if cycle limit doesn't prevent it.

## [0.4.0]

- Allow filtering out operations by id
- Use summary as fallback when description isn't present
- Add support for PUT, DELETE
- Add support for request body details, to support POST, PUT, etc.
- Include all parameters, not just required ones
- Using dicts instead of tuples so the meaning is clearer

## [0.1.2] - 2024-02-13

- Add maintainers and keywords from library.json (llamahub)
