import check_peers
import check_LOB
import check_panel
import openpyxl
import os
import pandas as pd
import time


start_time = time.time()
countryPeers = pd.read_excel("Final_Data/Final_MF.xlsx", sheet_name='Country Peers')
LOBMapping = pd.read_excel("Final_Data/Final_MF.xlsx", sheet_name='LOB Mapping')
userPanel = pd.read_excel("Final_Data/Final_MF.xlsx", sheet_name='User Panel')
countryPeers['Country'] = countryPeers['Country'].replace({'UK': 'United Kingdom', 'UAE': 'United Arab Emirates', 'Miami (BM)': 'Miami'})

peers_logs = check_peers.submit_changes(countryPeers)
no_LOB_matches = check_peers.no_LOB_mappings(countryPeers, LOBMapping)
# print(peers_logs)
LOB_logs = check_LOB.submit_changes(LOBMapping)
panel_logs = check_panel.submit_changes(userPanel)


if not os.path.exists("validation_results.xlsx"):
    wb = openpyxl.Workbook()
    wb.save("validation_results.xlsx")

writer = pd.ExcelWriter(
    path='validation_results.xlsx',
    engine='openpyxl',
    mode='a',                   
    if_sheet_exists='replace'   
)

if len(peers_logs)>0:
    peers_logs.to_excel(writer, sheet_name='Country Peers', index=False) 

if len(LOB_logs)>0:
    LOB_logs.to_excel(writer, sheet_name='LOB Mapping', index=False)  

if len(panel_logs)>0:
    panel_logs.to_excel(writer, sheet_name='User Panel', index=False)  

if len(no_LOB_matches)>0:
    no_LOB_matches.to_excel(writer, sheet_name='LOB Mismatch', index=False)  

writer.close()

end_time = time.time()
print(end_time - start_time)