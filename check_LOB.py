import pandas as pd

def submit_changes(edited_df):
    
    edited_df = edited_df.map(lambda x: x.strip() if type(x)==str else x)

    logs = pd.DataFrame(columns=['Country','Carrier Group','Carrier Name','Log'])

   
    # Data Validation
    for _,row in edited_df.iterrows():
        # If there is already an entry with same carrier name or carrier name is empty
        if row['Carrier Group'] in ['', None]:
            new_log = pd.DataFrame([{'Country':row['Country'],'Carrier Group':row['Carrier Group'], 'Carrier Name':row['Carrier Name'],'Log':"Carrier Group is empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)

        # If there is already an entry with same carrier name or carrier name is empty
        if row['Carrier Name'] in ['', None]:
            new_log = pd.DataFrame([{'Country':row['Country'],'Carrier Group':row['Carrier Group'], 'Carrier Name':row['Carrier Name'],'Log':"Carrier Name is empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)
            
        
        # Check if there at least one practice marked as X for each carrier
        if len(row[5:].dropna())==0:
            new_log = pd.DataFrame([{'Country':row['Country'],'Carrier Group':row['Carrier Group'], 'Carrier Name':row['Carrier Name'],'Log':"There is no practice for the carrier."}])
            logs = pd.concat([logs,new_log],ignore_index=True)

    return logs