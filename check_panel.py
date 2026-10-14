import pandas as pd
import numpy as np

def submit_changes(edited_df, filename, matchingIndex):

    edited_df = edited_df.map(lambda x: x.strip() if type(x)==str else x)
    logs = pd.DataFrame(columns=['Index', 'Country', 'Log'])
    
    for index, row in edited_df.iterrows():

        updatedIndex = index + matchingIndex + 3

        if row['Country'] in [None, '', np.nan]:
            country = filename.split("_")[0]
        else:
            country = row['Country']
        if row['Email'] in [None, '', np.nan]:
            new_log = pd.DataFrame([{'Index':updatedIndex, 'Country': country, 'Log':"Work Email cannot be empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)
        
        if row['Country'] in [None, '', np.nan]:
            new_log = pd.DataFrame([{'Index':updatedIndex, 'Country': country, 'Log':"Country cannot be empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)

        if row['Name'] in [None, '', np.nan]:
            new_log = pd.DataFrame([{'Index':updatedIndex, 'Country': country, 'Log':"Legal Name cannot be empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)
    
    return logs

