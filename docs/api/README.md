# `docs/api/`

**เจ้าของ:** คนที่ 2

Documentation about the public API that does not belong in the contract files themselves.

| Document | What it answers |
| --- | --- |
| [`field-ownership-matrix.md`](field-ownership-matrix.md) | Who may write each entity and field, and who only reads it. |

The contract itself lives in [`packages/contracts/`](../../packages/contracts/). Rendered reference
documentation is produced from `packages/contracts/openapi/public-api.yaml`; it is not committed
here, because a checked-in copy of generated docs drifts from the spec it describes.

```bash
cd packages/contracts
npx redocly preview-docs openapi/public-api.yaml     # browse the API locally
```

อ่านแผน: [`IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md)
