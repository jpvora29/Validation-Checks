import pandas as pd
import numpy as np

def submit_changes(edited_df, matchingIndex):
    
    edited_df = edited_df.map(lambda x: x.strip() if type(x)==str else x)

    logs = pd.DataFrame(columns=['Index', 'Country', 'Carrier Name', 'Log'])

   
    # Data Validation
    for index ,row in edited_df.iterrows():
        updatedIndex = index + matchingIndex + 3
        # If there is already an entry with same carrier name or carrier name is empty
        if row['Carrier Name'] in ['', None, np.nan]:
            new_log = pd.DataFrame([{'Index': updatedIndex, 
                                    'Country':row['Country'], 
                                    'Carrier Name':row['Carrier Name'],
                                    'Log':"Carrier Name is empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)
            
        
        # Check if there at least one practice marked as X for each carrier
        if len(row[5:].dropna())==0:
            new_log = pd.DataFrame([{'Index': updatedIndex,
                                    'Country':row['Country'], 
                                    'Carrier Name':row['Carrier Name'],
                                    'Log':"There is no practice for the carrier."}])
            logs = pd.concat([logs,new_log],ignore_index=True)

    return logs