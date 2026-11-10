# Third-party dependencies

The root MIT licence applies to this repository's original application source.
Third-party packages retain their own licences and conditions.

| Package | Use | Licence / distribution |
| --- | --- | --- |
| `ag-studio-react`, `ag-studio` | Interactive financial reports | Commercial; local evaluation and vendor trial/licensed hosted use |
| `ag-grid-enterprise`, `ag-charts-enterprise` | AG Studio's transitive grid/chart dependencies | Vendor commercial terms |
| `@bryntum/gantt-trial` (aliased to `@bryntum/gantt`) | Project milestone timeline | Commercial trial; vendor states a 45-day trial |
| `@bryntum/gantt-react` | React integration | Vendor commercial terms |
| PayPal/APIMatic Context Plugin | Developer reference tooling | MIT in the plugin manifest; separate external installation |
| `render` Python SDK | Read-only background cash-risk reports | Apache-2.0 |

Installed package licence files are the authoritative terms. Request the relevant
trial or production licences before hosted use and replace expired trial packages
with a licensed installation. Preserve vendor watermarks/notices. Do not commit
`node_modules` or copy vendor package sources into this repository.

Other dependencies and their licence metadata are recorded in package manifests
and lockfiles. Hosted Render deploy steps are in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
