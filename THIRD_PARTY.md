# Licenses and source correspondence

The original Python service, installation tools and root skill are offered under AGPL-3.0-only where the project author has the right to grant that license. `LICENSE` contains its text. Existing separately licensed components retain their licenses; the release does not relicense them.

| Component | Version / source | License | Distribution |
|---|---|---|---|
| Research Memory Obsidian adapter | Source in tools/obsidian/graph/plugin | GPL-3.0 | Source JS/CSS and plugin entry; LICENSE and NOTICE retained |
| Basic Memory | 0.23.2, https://github.com/basicmachines-co/basic-memory | AGPL-3.0 | Installed from the pinned upstream package; no private upstream checkout bundled |
| Juggl | 1.5.0, https://github.com/HEmile/juggl/tree/1.5.0 | GPL-3.0 | Optional external install for the local graph; not needed by the timeline |
| PathFinding.js | 0.4.18, https://github.com/qiao/PathFinding.js | MIT | Embedded in the existing adapter; notice retained |
| heap.js | 0.2.5, https://github.com/qiao/heap.js | PSF 2.7.2 | Used by the existing embedded graph helper; notice retained |
| FastMCP / Python dependencies | Exact versions in integrations/release-requirements.lock.txt | Upstream licenses | Installed separately by the package manager; upstream package notices retained |

The adapted public research-capture workflow draws on the MIT-licensed research-insight-vault protocol. This distribution contains its adaptation, not the author's original vault or private absolute paths. The experiment/source protocol is maintained in references/protocol.md.

Obsidian is proprietary software obtained separately. The release does not bundle its installer. Front Matter Title and Local REST API are existing optional integrations but are not automatically installed by this preview package.

Installing dependencies does not change their licenses. The fixed dependency list and release file hashes identify the shipped source and installation inputs. When distributing modified adapter builds, retain the corresponding editable source and notices.
