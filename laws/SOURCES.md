# Law library sources

Each folder holds the documents for one jurisdiction. The app indexes every PDF, TXT, CSV or Excel file in
`laws/<CODE>/` the first time someone picks that jurisdiction. `NYC` also searches `NY`.

Files ending in `_UNOFFICIAL_summary.txt` are plain-language restatements of official pages, made on
2026-11-22 because the build environment could not download government files directly. They fill gaps the
official manuals do not cover (mainly points tables). New documents can be added from the app's sidebar
(*Add official documents*) or by copying them into the folder.

| Folder | Document | In the library | Where to get it |
| --- | --- | --- | --- |
| CA | California Driver's Handbook | ✅ `ca_driver_handbook.pdf` | https://www.dmv.ca.gov/portal/handbook/california-driver-handbook/ |
| CA | Uniform Bail and Penalty Schedule, 2026 | ✅ `ca_uniform_bail_penalty_schedule_2026.pdf` | California Judicial Council / county superior court sites |
| NY | New York State Driver's Manual, MV-21 | ✅ `ny_drivers_manual_MV-21.pdf` | https://dmv.ny.gov/document/mv-21 |
| NY | Driver point system | Summary only | https://dmv.ny.gov/points-and-penalties/the-new-york-state-driver-point-system |
| NJ | New Jersey Driver Manual | ✅ `nj_driver_manual.pdf` | https://www.nj.gov/mvc/about/manuals.htm |
| NJ | Points schedule | Summary only | https://www.nj.gov/mvc/license/points-schedule.htm |
| NYC | Parking ticket brochure | ✅ `nyc_parking_brochure.pdf` | https://www.nyc.gov/assets/finance/downloads/pdf/brochures/parking_brochure.pdf |
| NYC | Parking violation codes and fines | ✅ `nyc_dof_parking_violation_codes.csv` plus summary | https://catalog.data.gov/dataset/dof-parking-violation-codes |
| VT | Vermont Driver's Manual, VN-007 | ✅ `vt_drivers_manual_VN-007.pdf` | https://dmv.vermont.gov/node/1377 |
| VT | Point schedule, 23 V.S.A. 2502 | Summary only | https://legislature.vermont.gov/statutes/section/23/025/02502 |
| SAMPLE | Fictional handbook, fine schedule (CSV) and point system (Excel) for demos. Not real law. | ✅ | Included |
