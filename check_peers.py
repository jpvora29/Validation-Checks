import pandas as pd
import numpy as np
import torch
from sentence_transformers import SentenceTransformer, util
import pandas as pd
import os

model_path = os.path.join(os.getcwd(), "paraphrase_MiniLM-L6-v2")
model = SentenceTransformer(model_path)


# Cleaning of each carrier name
def replace_all(text):
    if type(text)==str:
        return text.lower().strip().replace(' (','(').replace('  ',' ')
    else:
        return text
    

# def find_best_match(all_LOB_carriers, carrier):
#     reference_embeddings = np.array([model.encode(name) for name in all_LOB_carriers])
#     best_match = ""
#     original_embeddings = model.encode(carrier)
#     # Creating cosine similarity matrix
#     try:
#         similarities = util.pytorch_cos_sim(torch.tensor(original_embeddings), torch.tensor(reference_embeddings)).numpy()
#         # Creating a list of cleaned client list 
#         threshold = 0.5
#         max_similarity_indices = np.argmax(similarities, axis=1)
#         mask = similarities[np.arange(len(similarities)), max_similarity_indices] >= threshold
#         for i, max_sim_idx in enumerate(max_similarity_indices):
#             if mask[i] and 0 <= max_sim_idx < len(all_LOB_carriers):
#                 reference_client = all_LOB_carriers[max_sim_idx]
#                 best_match = reference_client
#     except:
#         pass
#     return best_match.upper()


def submit_changes(peers_df, matchingIndex):
    
    peers_df = peers_df.map(lambda x: x.strip() if type(x)==str else x)
    logs = pd.DataFrame(columns=['Index', 'Country', 'Carrier Group', 'Carrier Name', 'Log'])

    # Data Validation
    for index, row in peers_df.iterrows():
        updatedIndex = index + matchingIndex + 3
        # If there is already an entry with same carrier name or carrier name is empty
        if row['Carrier Group'] in ['', None, np.nan]:
            new_log = pd.DataFrame([{'Index': updatedIndex, 
                                    'Country':row['Country'],
                                    'Carrier Group':row['Carrier Group'], 
                                    'Carrier Name':row['Carrier Name'],
                                    'Log':"Carrier Group is empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)
            
        
        # If there is already an entry with same carrier name or carrier name is empty
        if row['Carrier Name'] in ['', None, np.nan]:
            new_log = pd.DataFrame([{'Index': updatedIndex, 
                                    'Country':row['Country'],
                                    'Carrier Group':row['Carrier Group'], 
                                    'Carrier Name':row['Carrier Name'], 
                                    'Log':"Carrier Name is empty!!"}])
            logs = pd.concat([logs,new_log],ignore_index=True)
            
        
        # There should be minimum of 5 peers ( 5 peers can be anywhere )
        all_peers = [x.upper() for x in row[6:] if type(x)==str] 
        if len(set(all_peers))<5:
            new_log = pd.DataFrame([{'Index': updatedIndex, 'Country':row['Country'],
                                     'Carrier Group':row['Carrier Group'], 
                                     'Carrier Name':row['Carrier Name'],
                                     'Log':f"Minimum of 5 peers not there"}])
            logs = pd.concat([logs,new_log],ignore_index=True)
            
        
        # If there are duplicate peers for same carrier name
        if len(set(all_peers)) != len(all_peers):
            new_log = pd.DataFrame([{'Index': updatedIndex, 
                                     'Country':row['Country'],
                                     'Carrier Group':row['Carrier Group'], 
                                     'Carrier Name':row['Carrier Name'],
                                     'Log':"There is a duplicate peer"}])
            logs = pd.concat([logs,new_log],ignore_index=True)



    



    # print(not_matching)


    return logs


def no_LOB_mappings(df_peers, df_LOB):
    not_matching = {}
    for i in df_peers['Country']:
        not_matching[i] = []
        
    for _,row in df_peers.iterrows():

        all_peers = [x.upper() for x in row[6:] if type(x)==str] 
        all_carriers = [row['Carrier Name']] + list(set(all_peers))
        all_carriers = [replace_all(i) for i in all_carriers]

        all_LOB_carriers = list(df_LOB[df_LOB['Country']==row['Country']]['Carrier Name'])
        #all_LOB_carriers += list(df_LOB[df_LOB['Country']==row['Country']]['Carrier Group'])
        all_LOB_carriers = [replace_all(i) for i in all_LOB_carriers]
        all_LOB_carriers = list(set(all_LOB_carriers))
        for i in all_carriers:
            if i not in all_LOB_carriers and type(i)==str:
                if  i not in not_matching[row['Country']]:
                    not_matching[row['Country']].append(i)

    pairs = []
    # Encoding the data
    for country,pair in not_matching.items():
        all_LOB_carriers = list(df_LOB[(df_LOB['Country']==country) & (df_LOB['Carrier Name'].notna())]['Carrier Name'])
        
        #all_LOB_carriers += list(df_LOB[df_LOB['Country']==country]['Carrier Group'])
        reference_embeddings = np.array([model.encode(name) for name in all_LOB_carriers])
        
        for carrier in pair:
            original_embeddings = model.encode(carrier)
            # Creating cosine similarity matrix
            try:
                similarities = util.pytorch_cos_sim(torch.tensor(original_embeddings), torch.tensor(reference_embeddings)).numpy()
                # Creating a list of cleaned client list 
                threshold = 0.5
                max_similarity_indices = np.argmax(similarities, axis=1)
                mask = similarities[np.arange(len(similarities)), max_similarity_indices] >= threshold
                for i, max_sim_idx in enumerate(max_similarity_indices):
                    if mask[i] and 0 <= max_sim_idx < len(df_LOB):
                        original_client = carrier
                        reference_client = all_LOB_carriers[max_sim_idx]
                    
                        pairs.append((country, original_client.upper(), reference_client))
            except:
                print(country, carrier)


    final = pd.DataFrame(pairs, columns=['Country', 'Country Peers', 'Country LOB'])
    return final
        # final['Score'] = final['Score'][0]
        # final.to_csv('final.csv')
        # all_carriers = [row['Carrier Name']] + list(set(all_peers))
        # all_carriers = [replace_all(i) for i in all_carriers]
        # not_matching = []
        # all_LOB_carriers = list(LOB_df[LOB_df['Country']==row['Country']]['Carrier Name'])
        # all_LOB_carriers += list(LOB_df[LOB_df['Country']==row['Country']]['Carrier Group'])
        # all_LOB_carriers = [replace_all(i) for i in all_LOB_carriers]
        # all_LOB_carriers = list(set(all_LOB_carriers))
        # for i in all_carriers:
        #     if i not in all_LOB_carriers and type(i)==str:
        #         not_matching.append(i)

        # if len(not_matching)>0:
        #     for j in not_matching:
        #         if f"No exact match found in LOB of carrier {j.upper()}" not in list(logs[logs['Country']==row['Country']]['Log']):
        #             new_log = pd.DataFrame([{'Country':row['Country'],'Carrier Group':row['Carrier Group'], 'Carrier Name':row['Carrier Name'],'Log':f"No exact match found in LOB of carrier {j.upper()}", "Possible Match": find_best_match(all_LOB_carriers, j)}])
        #             logs = pd.concat([logs,new_log],ignore_index=True)