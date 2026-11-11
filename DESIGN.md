# Publication Workbench design

The editor is an Operate surface: a contents rail, working form, and review/publish column. The exported program is a Read surface with internal section links.

The visual direction takes its type, palette, density, and signature from a community printmaking program: warm paper, leaf-green ink, restrained serif program titles, and fine rules. The signature is a clearly sequenced proof-to-publication column beside the editable copy. Controls and navigation remain conventional web components.

## Tokens

| Token | Value | Use |
|---|---|---|
| Paper | `#f6f4ec` | Application ground |
| White | `#fffef9` | Editable surface |
| Ink | `#28342b` | Primary text |
| Muted | `#5d685b` | Supporting text |
| Line | `#c6ccbe` | Separators |
| Green | `#365b35` | Actions and links |
| Green dark | `#254324` | Hover |
| Soft green | `#e6ecdf` | Selected content |
| Error | `#953626` | Validation and failure |
| Focus | `#9a6718` | Visible keyboard outline |

System sans at 16px is used for controls; Georgia gives only program/title text an editorial voice. Spacing uses quarter-rem increments. Controls have modest 3–4px radii and at least 42px height. No imagery, external fonts, or decorative animation is required.

At 1050px the review column moves below the editor; at 640px the contents become wrapping controls above a single-column form. Motion is limited to short control feedback and respects reduced-motion preferences. Error text is explicit and publication state is represented in words, not color alone.

The brief authorized direct implementation without a visual interview or browser inspection. Source checks do not constitute rendered visual verification.
