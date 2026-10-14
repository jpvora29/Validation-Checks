import openpyxl
import os
import pandas as pd
import time
import check_peers
import test_check_LOB
import check_panel
import check_new_peers
import numpy as np

start_time = time.time()

def cleanData(data: pd.DataFrame, pattern: str) -> pd.DataFrame | int:

    '''Returns the clean data by finding the column headers using regex pattern'''

    # Getting the Index where data contains the pattern
    matchingIndex = data.apply(lambda row: row.astype(str).str.contains(pattern).any(), axis=1).idxmax()
    data.columns = data.iloc[matchingIndex]
    
    # If all columns in data are None
    if data.columns.all() == None:
        return None

    else:
        data.rename_axis(None, axis=1, inplace=True)
        cleanData = data.iloc[matchingIndex + 1:].reset_index(drop=True)
        
        return cleanData, matchingIndex


def getData(dataDict: dict, pattern: str, filename: str) -> pd.DataFrame | int:

    '''Return the respective sheet data along with a error Log'''

    errorLog = pd.DataFrame(columns=['Country', 'Sheet Name', 'Error'])

    for key in dataDict.keys():
        if key == '1.Country Peers':
            countryPeers = dataDict[key]
            countryPeers, peersMatchingIndex  = cleanData(data=countryPeers, pattern=pattern)
            country = countryPeers['Country'].unique()[0]
            
            if len(countryPeers) == 0:
                newLog = pd.DataFrame([{
                    'Country': country,
                    'Sheet Name': key,
                    'Error': 'The Pattern does not match desired columns'
                }])
                
                errorLog = pd.concat([errorLog, newLog], ignore_index=True)
        
        elif key == '2. Country LOB MAPPING.':
            countryLOB = dataDict[key]
            countryLOB, LOBMatchingIndex = cleanData(data=countryLOB, pattern=pattern)
            country = countryLOB['Country'].unique()[0]

            if len(countryPeers) == 0:
                newLog = pd.DataFrame([{
                    'Country': country,
                    'Sheet Name': key,
                    'Error': 'The Pattern does not match desired columns'
                }])

                errorLog = pd.concat([errorLog, newLog], ignore_index=True)
        
        elif key == '3. User Panel':
            userPanel = dataDict[key]
            userPanel, panelMatchingIndex = cleanData(data=userPanel, pattern=pattern)
            country = userPanel['Country'].unique()[0]

            if len(userPanel) == 0:
                newLog = pd.DataFrame([{
                    'Country': country,
                    'Sheet Name': key,
                    'Error': 'The Pattern does not match desired columns'
                }])

                errorLog = pd.concat([errorLog, newLog], ignore_index=True)

        # Sheet Name not matching
        else:
            country = filename.split("_")[0]

            newLog = pd.DataFrame([{
                'Country': country,
                'Sheet Name': None,
                'Error': 'Name Mismatch in sheet name'
            }])

    return countryPeers, countryLOB, userPanel, errorLog, peersMatchingIndex, LOBMatchingIndex, panelMatchingIndex

       
def renamingColumns(data: pd.DataFrame, sheet: str = "3. User Panel") -> pd.DataFrame:

    '''Renames certain column names and returns the updated dataframe'''

    if sheet == "1.Country Peers":
        carrierName = data.columns[np.where(data.columns.str.contains(r'Carrier\s?Name'))][0]
        carrierGroup = data.columns[np.where(data.columns.str.contains(r'Carrier\s?Group'))][0]

        data.rename({
            carrierName: "Carrier Name",
            carrierGroup: "Carrier Group"
        }, axis=1, inplace=True)
    
    elif sheet == "2. Country LOB MAPPING.":
        carrierName = data.columns[np.where(data.columns.str.contains(r'\bCarrier\b'))][0]
        
        data.rename({
            carrierName: "Carrier Name"
        }, axis=1, inplace=True)
    
    else:

        # Convert the column names to string datatype
        data.columns = data.columns.astype(str)

        name = data.columns[np.where(data.columns.str.contains(r'\bLegal\s?Name\b|(?<![\w\s-])\bName\b(?![\w\s-])'))][0]
        email = data.columns[np.where(data.columns.str.contains(r'\bWork\s?Email\b|\bEmail\b'))][0]
        
        data.rename({
            name: "Name",
            email: "Email"
        }, axis=1, inplace=True)
    
    return data


# Filepath where the country-wise files are stored
filepath = os.path.join(os.getcwd(), "Country-Wise To Be Validated Files")

# Initializing the dataframes
allPeersLogs = pd.DataFrame()
allNewPeersLogs = pd.DataFrame()
allNoLOBMatches = pd.DataFrame()
allLOBLogs = pd.DataFrame()
allPanelLogs = pd.DataFrame()
allErrorLogs = pd.DataFrame()

fileError = pd.DataFrame(columns=['FileName', 'Error Message'])


if len(os.listdir(filepath)) > 0:
    for file in os.listdir(filepath):
        #try:
            print(file)

            # Checking if the file name format is incorrect
            if "Carrier_Survey" not in file:
                errorMessage = pd.DataFrame([{
                    'FileName': file,
                    'Error': 'File Name Format is incorrect.'
                }])
                fileError = pd.concat([fileError, errorMessage], ignore_index=True)

                continue
            
            # Reading the dataframe and its stored as dictionary where key is sheet name and value is data
            dataDict = pd.read_excel(os.path.join(filepath, file), sheet_name=None)

            # Pattern to identify the column headers
            pattern = r'\bRegion\b|\bCountry\b|\bPeer \d+\b|\bEmployee ID\b|\bWork Email\b|\bEmail\b'

            # Getting Correctly Formatted Data
            countryPeers, countryLOB, userPanel, errorLog, peersMatchingIndex, LOBMatchingIndex, panelMatchingIndex = getData(dataDict=dataDict, 
                                                                                pattern=pattern, filename=file)
            # Renaming Few Columns for Standarization
            countryPeers = renamingColumns(data=countryPeers, sheet="1.Country Peers")
            countryLOB = renamingColumns(data=countryLOB, sheet="2. Country LOB MAPPING.")
            userPanel = renamingColumns(data=userPanel)

            # if file == 'Belgium_Carrier_Survey_2025_Validation.xlsx':
            #     print(countryLOB['Carrier Name'])


            # if file == "Philippines_Carrier_Survey_2025_Validation.xlsx":
            #     print(countryPeers.to_csv("Temp.csv"), index=False)

            # Validation checks
            peers_logs = check_peers.submit_changes(countryPeers, peersMatchingIndex)
            new_peers_logs = check_new_peers.submit_changes(countryPeers, countryLOB)
            no_LOB_matches = check_peers.no_LOB_mappings(countryPeers, countryLOB)
            LOB_logs = test_check_LOB.submit_changes(countryLOB, LOBMatchingIndex)
            panel_logs = check_panel.submit_changes(userPanel, file, panelMatchingIndex)
            

            # Concatenating all files data
            allPeersLogs = pd.concat([allPeersLogs, peers_logs], ignore_index=True)
            allNewPeersLogs = pd.concat([allNewPeersLogs, new_peers_logs], ignore_index=True)
            allNoLOBMatches = pd.concat([allNoLOBMatches, no_LOB_matches], ignore_index=True)
            allLOBLogs = pd.concat([allLOBLogs, LOB_logs], ignore_index=True)
            allPanelLogs = pd.concat([allPanelLogs, panel_logs], ignore_index=True)
            allErrorLogs = pd.concat([allErrorLogs, errorLog], ignore_index=True)
        
        # except:
        #     errorMessage = pd.DataFrame([{
        #         'FileName': file,
        #         'Error Message': 'Formatting issue in file.'
        #     }])
            
        #     fileError = pd.concat([fileError, errorMessage], ignore_index=True)

        #     continue
        

    outputPath = os.path.join(os.getcwd(), "Output File")

    if not os.path.exists(os.path.join(outputPath, "validation_results.xlsx")):
        wb = openpyxl.Workbook()
        wb.save(os.path.join(outputPath, "validation_results.xlsx"))
    

    writer = pd.ExcelWriter(
        path=os.path.join(outputPath, 'validation_results.xlsx'),
        engine='openpyxl',
        mode='a',                   
        if_sheet_exists='replace'   
    )

    if len(allPeersLogs) > 0:
        allPeersLogs.to_excel(writer, sheet_name='Country Peers', index=False)
    
    if len(allNewPeersLogs) > 0:
        allNewPeersLogs.to_excel(writer, sheet_name='New Peers', index=False)

    if len(allLOBLogs) > 0:
        allLOBLogs.to_excel(writer, sheet_name='LOB Mapping', index=False)  

    if len(allPanelLogs) > 0:
        allPanelLogs.to_excel(writer, sheet_name='User Panel', index=False)  

    if len(allNoLOBMatches) > 0:
        allNoLOBMatches.to_excel(writer, sheet_name='LOB Mismatch', index=False)  

    writer.close()


    if not os.path.exists(os.path.join(outputPath, "errorLogs.xlsx")):
        wb = openpyxl.Workbook()
        wb.save(os.path.join(outputPath, "errorLogs.xlsx"))

    errorWriter = pd.ExcelWriter(
        path=os.path.join(outputPath, 'errorLogs.xlsx'),
        engine='openpyxl',
        mode='a',                   
        if_sheet_exists='replace'   
    )

    if len(allErrorLogs) > 0:
        allErrorLogs.to_excel(errorWriter, sheet_name="File Pattern Mismatch", index=False)

    if len(fileError) > 0:
        fileError.to_excel(errorWriter, sheet_name="File Not Searched", index=False)
    
    errorWriter.close()

else:
    raise Exception("No Files Found in the mentioned path.")
        