import pandas as pd
import numpy as np
import uuid
import os
import logging
import json as json_package
import re
import platform

from .utils import get_uniprot_seqs
from .gget_diamond import diamond

from .constants import (
    ELM_CLASSES_TSV,
    ELM_INSTANCES_FASTA,
    ELM_INSTANCES_TSV,
    UNIPROT_REST_API,
)
# Custom functions
from .compile import PACKAGE_PATH



# Path to precompiled diamond binary
if platform.system() == "Windows":
    PRECOMPILED_DIAMOND_PATH = os.path.join(
        PACKAGE_PATH, f"bins/{platform.system()}/diamond.exe"
    )
else:
    PRECOMPILED_DIAMOND_PATH = os.path.join(
        PACKAGE_PATH, f"bins/{platform.system()}/diamond"
    )

def motif_in_query(row):
    return True if (row["Start"] >= row["target_start"]) & (row["End"] <= row["target_end"]) else False

def tsv_to_df(tsv_file, headers = None):
    try:
        df = pd.DataFrame()
        if headers:
            df = pd.read_csv(tsv_file, sep="\t", names=headers)
        else:
            df = pd.read_csv(tsv_file, sep="\t")
        return df


    except pd.errors.EmptyDataError:
        logging.warning(f"Query did not result in any matches.")
        return None


def get_elm_instances(UniProtID, elm_instances_tsv, elm_classes_tsv, verbose):
    #check if local elm files are installed
    try:
        import elm_files
        if verbose:
            logging.info(f"elm files installed succesfully.")
    except ImportError as e:
        logging.error(
            f"ELM files not found.  Please run the following command: >>> gget.setup('elm') or $ gget setup elm"
        )
        return

    # return matching rows from elm_instances.tsv
    df_full_instances = tsv_to_df(elm_instances_tsv)
    df_full_instances.rename(columns = {'Accession':'UniProt ID'}, inplace = True)
    df_full_instances.rename(columns = {'Start in ortholog':'Start'}, inplace = True)
    df_full_instances.rename(columns = {'End in ortholog':'End'}, inplace = True)
    df_instances_matching = df_full_instances.loc[df_full_instances['Accessions'].str.contains(UniProtID)]

    # get class descriptions from elm_classes.tsv
    df_classes = tsv_to_df(elm_classes_tsv)
    df_classes.rename(columns = {'Accession':'class_accession'}, inplace = True)



    #merge two dataframes using ELM Identifier
    df = df_instances_matching.merge(df_classes, how='left', on=['ELMIdentifier'])
    #reorder columns 
    change_column= ["UniProt ID","class_accession", "ELMIdentifier", "FunctionalSiteName", "Description", "Regex", "Probability", "Start in ortholog", "End in ortholog", "Query Cover", "Per. Ident", "query_start", "query_end", "target_start", "target_end","ProteinName", "Organism", "References", "InstanceLogic", "PDB", "#Instances", "#Instances_in_PDB"]
    df_final = df.reindex(columns=change_column)
    return df_final


def seq_workflow(sequences, sequence_lengths, verbose):
    df = pd.DataFrame()
    seq_number = 1
    for sequence, seq_len in zip(sequences, sequence_lengths):
        sequence = str(sequence)
        with open(f"tmp{str(uuid.uuid4())}.fa", "w") as f:
            f.write("> \n" + sequence)
        
        diamond(f"{os. getcwd()}tmp{str(uuid.uuid4())}.fa", ELM_INSTANCES_FASTA)
        df_diamond = tsv_to_df("diamond_out.tsv", ["query_accession", "target_accession", "Per. Ident" , "length", "mismatches", "gap_openings", "query_start", "query_end", "target_start", "target_end", "e-value", "bit_score"])
        
        # If no match found for sequence, raise error
        if (len(df_diamond) == 0):
            logging.warning(f"Sequence #{seq_number}: No matching sequences found in ELM database.")
        else:
            logging.info(f"Sequence #{seq_number}: Found similar sequences. Retrieving data about corresponding ELMs...")

            # Construct df with elm instances from uniprot ID returned from diamond 
            uniprot_ids = []
            uniprot_ids.append(str(df_diamond["target_accession"]).split('|')[1])
            logging.info(f"Pairwise sequence alignment with DIAMOND matched the following UniProt IDs {uniprot_ids}. Retrieving ELMs for each UniProt ID...")

            for id in uniprot_ids:
                df_elm = get_elm_instances(id, ELM_INSTANCES_TSV, ELM_CLASSES_TSV, verbose)
                df_elm["Query Cover"] = df_diamond["length"] / seq_len * 100
                df_elm["Per. Ident"] = df_diamond["Per. Ident"]
                df_elm["query_start"] = df_diamond["query_start"]
                df_elm["query_end"] = df_diamond["query_end"]
                df_elm["target_start"] = df_diamond["target_start"]
                df_elm["target_end"] = df_diamond["target_end"]
                df_elm["motif_in_query"] = df_elm.apply(motif_in_query, axis=1)
    
                df = pd.concat([df, df_elm])

        seq_number += 1

    return df 

def regex_match(sequence):
    #Get all motif regex patterns from elm db local file
    df_elm_classes = tsv_to_df(ELM_CLASSES_TSV)
    df_full_instances = tsv_to_df(ELM_INSTANCES_TSV)

    elm_ids = df_elm_classes["Accession"]

    regex_patterns = df_elm_classes["Regex"]

    #Compare elm regex with input sequence and return all matching elms
    for elm_id, pattern in zip(elm_ids, regex_patterns):

        regex_matches = re.finditer(pattern, sequence)


        for match_string in regex_matches:
            
            elm_row = df_elm_classes.loc[df_elm_classes["Accession"]== elm_id]
      
            elm_row.insert(loc=1, column='Instances (Matched Sequence)', value=match_string.group(0))

            (start, end) = match_string.span()
            elm_row.insert(loc=2, column='Start in query', value=str(start))
            elm_row.insert(loc=3, column='End in query', value=str(end))
        
           
            elm_identifier = [str(x) for x in elm_row["ELMIdentifier"]][0]
  
            df_instances_matching = df_full_instances.loc[df_full_instances['ELMIdentifier']==elm_identifier]
   

            #merge two dataframes using ELM Identifier, since some Accessions are missing from elm_instances.tsv
            
            df_final = elm_row.merge(df_instances_matching, how='left', on=['ELMIdentifier'])
            
            df_final.pop("Accession_y")
            df_final.pop("#Instances")
            df_final.pop("#Instances_in_PDB")
            df_final.pop("References")
            df_final.pop("InstanceLogic")


  

    df_final.rename(columns = {'Accession_x':'instance_accession'}, inplace = True)
  
    change_column = ['instance_accession',"ELMIdentifier", "FunctionalSiteName", "ELMType", "Description", 'Instances (Matched Sequence)', "Probability", "Start in ortholog", "End in ortholog","Methods", "ProteinName", "Organism"]
    df_final = df_final.reindex(columns=change_column)
    return df_final

def elm(sequence, uniprot=False, json=False, verbose=True, out=None):
    """
    Searches the Eukaryotic Linear Motif resource for Functional Sites in Proteins.

    Args:
     - sequence       amino acid sequence or Uniprot ID
     - uniprot        If True, searches using Uniprot ID instead of amino acid sequence. Default: False
     - json           If True, returns results in json format instead of data frame. Default: False.
     - out            folder name to save two resulting csv files. Default: results (default: None).
     - verbose        True/False whether to print progress information. Default True.
  
    Returns two data frames: orthologs and regex matches from ELM results.
    """


    if not uniprot:
        amino_acids = set("ARNDCQEGHILKMFPSTWYVBZXBJZ")
        # Convert input sequence to upper case letters
        sequence = sequence.upper()

        # If sequence is not a valid amino sequence, raise error
        if not set(sequence) <= amino_acids:
            logging.warning(
                f"Input amino acid sequence contains invalid characters. If the input is a UniProt ID, please specify `uniprot=True` (python: uniprot=True)."
            )

    df = pd.DataFrame()

    if uniprot:
        df_temp = get_elm_instances(sequence, ELM_INSTANCES_TSV, ELM_CLASSES_TSV, verbose)
        df = pd.concat([df, df_temp])
        df["Query Cover"] = np.nan
        df["Per. Ident"] = np.nan
        if (len(df) == 0):
            logging.warning("UniProt ID does not match any results in elm database. Converting UniProt ID to amino acid sequence...")
            df_uniprot = get_uniprot_seqs(server=UNIPROT_REST_API, ensembl_ids=sequence)
            try:
                #only grab sequences where id match exact input uniprot id
                aa_seqs = df_uniprot[df_uniprot["uniprot_id"] == id]["sequence"].values
                seq_lens = df_uniprot["sequence_length"].values
            except KeyError:
                raise ValueError(f"No sequences found for UniProt ID {sequence} from searching the UniProt server. Please double check your UniProt ID and try again.")
                
    if len(df) == 0:
        # add input aa sequence and its length to list
        if not uniprot:
            aa_seqs = [sequence]
            seq_lens = [len(sequence)]
        if verbose:
            logging.info(f"Performing pairwise sequence alignment against ELM database using DIAMOND for {len(aa_seqs)} sequence(s)...")
        df = pd.concat([df, seq_workflow(aa_seqs, seq_lens, verbose)])
        
        if (len(df) == 0):
            logging.warning("No orthologs found for sequence or UniProt ID input")
        
        if not uniprot and len(df) > 0:
            try:
                target_start = df['target_start'].values.tolist()
                target_end = df['target_end'].values.tolist()
        
                if (df["Per. Ident"] is not None):
                    # ignore nonoverlapping motifs
                    df.drop(df[ (df['Start'] <= target_start[0]) | (df['End'] >= target_end[0]) ].index, inplace=True)
            except KeyError:
                logging.warning("No target start found for input sequence. If you entered a UniProt ID, please set 'uniprot' flag to True.")
    
    if uniprot:
        #use amino acid sequence associated with UniProt ID to do regex match
        df_uniprot = get_uniprot_seqs(UNIPROT_REST_API, sequence)
        sequences = df_uniprot[df_uniprot["uniprot_id"] == sequence]["sequence"].values
        sequence = sequences[0]

    # find exact motifs
    df_regex_matches = regex_match(sequence)
    if (len(df_regex_matches) == 0):
        logging.warning("No regex matches found for sequence or UniProt ID input")
   
    # for terminal main.py, check if instance(df, None) 

    if json:
        ortholog_dict = json_package.loads(df.to_json(orient="records"))
        regex_dict = json_package.loads(df_regex_matches.to_json(orient="records"))
        if out:
            with open("ortholog.json", "w", encoding="utf-8") as f:
                json_package.dump(ortholog_dict, f, ensure_ascii=False, indent=4)
            with open("regex.json", "w", encoding="utf-8") as f:
                json_package.dump(regex_dict, f, ensure_ascii=False, indent=4)

        if (len(df) > 0 and len(df_regex_matches) > 0):
            return ortholog_dict, regex_dict

        elif (len(df) > 0):
            return ortholog_dict
        elif (len(df_regex_matches) > 0):
            return regex_dict

    else:
        ROOT_DIR = os.path.abspath(os.curdir)
        if out is None:
            # Create temporary results folder
            path = os.path.join(ROOT_DIR, "results")
        else:
            path = os.path.join(ROOT_DIR, out)
        try:

            
            if (len(df) > 0 and len(df_regex_matches) > 0):   
                df.to_csv(os.path.join(path,"ortholog"))
                df_regex_matches.to_csv(os.path.join(path,"regex_match"))
            elif (len(df) > 0):
                df.to_csv(os.path.join(path,"ortholog"))
            elif (len(df_regex_matches) > 0):
                df_regex_matches.to_csv(os.path.join(path,"regex_match"))

            
        except OSError: 
            os.mkdir(path)

    
    if (len(df) > 0 and len(df_regex_matches) > 0):
        return df, df_regex_matches
    elif (len(df) > 0):
        return df
    elif (len(df_regex_matches) > 0):
        return df_regex_matches
