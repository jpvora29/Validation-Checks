import pandas as pd
import numpy as np
import os

# Cleaning of each carrier name
def replace_all(text):
    if type(text)==str:
        return text.lower().strip().replace(' (','(').replace('  ',' ')
    else:
        return text
    

def submit_changes(df_peers, df_LOB):
    
    country = df_peers['Country'].unique()[0]
    newPeers = []
    allCountryPeersCarriers = []

    # To Include only those records which have string datatype for Carrier Name
    filtered_df = df_peers[df_peers['Carrier Name'].apply(lambda x: isinstance(x, str))]
    

    for _, row in filtered_df.iterrows():
        all_peers = [x.upper() for x in row[6:] if type(x)==str]
        all_carriers = [row['Carrier Name']] + list(set(all_peers))
        all_carriers = [replace_all(i) for i in all_carriers]

        allCountryPeersCarriers.extend(all_carriers)

        all_LOB_carriers = list(df_LOB[df_LOB['Country']==country]['Carrier Name'])
        
        #all_LOB_carriers += list(df_LOB[df_LOB['Country']==row['Country']]['Carrier Group'])
        all_LOB_carriers = [replace_all(i) for i in all_LOB_carriers]

 
    if set(allCountryPeersCarriers) != set(all_LOB_carriers):

        for ele in set(allCountryPeersCarriers):
            if ele not in all_LOB_carriers:
                newPeers.append(ele.upper())
                
                
        logs = pd.DataFrame([{'Country':country,
                              'New Peers': newPeers,
                              'Log':"This are new Peers which are not present in LOB sheet"}])

        return logs