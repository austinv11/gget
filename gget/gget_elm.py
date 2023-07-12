import requests
import pandas as pd
import numpy as np
import logging
from bs4 import BeautifulSoup
from io import StringIO
import json as json_package
import time

# Add and format time stamp in logging messages
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    datefmt="%c",
)
# Mute numexpr threads info
logging.getLogger("numexpr").setLevel(logging.WARNING)

# Constants
from .constants import GET_ELM_API, ELM_URL


# Call elm api to get elm id, start, stop and boolean values
# Returns tab separated values
def get_response_api(seq):
    # Build URL
    html = requests.get(GET_ELM_API + seq)

    # Incorrect UniProt ID results in 500 internal server error
    if html.status_code == 500:
        raise RuntimeError(
            f"The ELM server returned error status code {html.status_code}. Please double-check the input UniProt ID and try again."
        )
    # Raise error if server
    elif html.status_code == 429:
        raise RuntimeError(
            f"The ELM server returned error status code {html.status_code}. Please wait 1 min (or 3 min for UniProt IDs) before submitting the next request."
        )
    # Raise error if status code not "OK" Response
    elif html.status_code != 200:
        raise RuntimeError(
            f"The ELM server returned error status code {html.status_code}. Please try again."
        )

    soup = BeautifulSoup(html.text, "html.parser")
    soup_string = str(soup)
    return soup_string


def tsv_to_df(tab_separated_values, sequence_if_fails):
    try:
        df = pd.DataFrame()
        df = pd.read_csv(StringIO(tab_separated_values), sep="\t")
        return df

    except pd.errors.EmptyDataError:
        logging.warning(f"Query did not result in any matches.")
        return None


# Scrapes webpage for information about functional site class, description, pattern probability
# Return html tags in text format
def get_html(elm_id):
    resp = requests.get(ELM_URL + elm_id)

    # Raise error if status code not "OK" Response
    # Incorrect elm id results in 500 internal server error
    if resp.status_code != 200:
        logging.warning(f"No additional information found for ELM ID {elm_id}.")
        html = ""

    else:
        html = resp.text

    return html


# Searches through separated tab values soup for tags corresponding to field param
# Return text string inside html tags
def get_additional_info(field, soup):
    if field == "Interaction Domain:":
        info = soup.find(id="interaction_domain").findNext("td").text
    else:
        info = soup.find(text=field).findNext("td").text
    return info


def elm(sequence, uniprot=False, json=False, save=False, verbose=True):
    """
    Searches the Eukaryotic Linear Motif resource for Functional Sites in Proteins.
    Args:
     - sequence       amino acid sequence or Uniprot ID
                      (If more than one sequence in FASTA file, only the first will be submitted to BLAST.)
     - uniprot        If True, searches using Uniprot ID instead of amino acid sequence. Default: False
     - json           If True, returns results in json format instead of data frame. Default: False.
     - save           If True, the data frame is saved as a csv in the current directory (default: False).
    - verbose         True/False whether to print progress information. Default True.

    Returns a data frame with the ELM results.

    NOTE: Please limit your searches to a maximum of 1 per minute for amino acid sequences (1 per 3 minutes for Uniprot IDs).
    If you exceed this limit, you will recieve a "429 Too many requests" error.
    Also please note that this does not always work for sequences longer than 2000 amino acids: URLs may be truncated beyond this length.

    """

    # Note: If you encounter 429 error, try adding time.sleep() to get_response_api()
    # Ex: import time
    # def get_response_api(seq, uniprot):
    # sleep_time = 65
    # if (uniprot):
    #     sleep_time = sleep_time * 3
    # url = "http://elm.eu.org/start_search/"
    # # Build URL
    # try:
    #     time.sleep(sleep_time)
    #     html = requests.get(url + seq)
    # except RuntimeError:
    #     time.sleep(sleep_time)
    #     html = requests.get(url + seq)

    if not uniprot:
        amino_acids = set("ARNDCQEGHILKMFPSTWYVBZXBJZ")

        # Convert input sequence to upper case letters
        sequence = sequence.upper()

        # If sequence is not a valid amino sequence, raise error
        if not set(sequence) <= amino_acids:
            logging.warning(
                f"Input amino acid sequence contains invalid characters. If the input is a UniProt ID, please specify `uniprot=True`."
            )

    if uniprot:
        sequence = sequence + ".tsv"

    if verbose:
        logging.info(f"Submitting API request to server...")

    tab_separated_values = get_response_api(sequence)

    df = tsv_to_df(tab_separated_values, sequence)

    if isinstance(df, type(None)):
        return df

    column_names = [
        "Accession:",
        "Functional site class:",
        "Functional site description:",
        "ELM Description:",
        "ELMs with same func. site:",
        "Pattern:",
        "Pattern Probability:",
        "Present in taxons:",
        "Interaction Domain:",
    ]

    # Creates new dataframe to store information from scraping
    df_2 = pd.DataFrame()
    # Grab elm identifiers column from dataframe
    elm_ids = df["elm_identifier"].values

    # Remove duplicate IDs
    elm_ids = list(set(elm_ids))

    # Add column of elm identifiers to new dataframe
    df_2["elm_identifier"] = elm_ids

    # Index dataframe using ELM id
    df_2 = df_2.set_index("elm_identifier")

    # Loop through each elm identifier, get and parse html content
    for elm_id_index, elm_id in enumerate(elm_ids):
        html = get_html(elm_id)
        soup = BeautifulSoup(html, "html.parser")
        for column in column_names:
            value = np.nan
            column_ignored_colon = column[:-1]
            try:
                value = get_additional_info(column, soup)
            except AttributeError:
                if column == "Present in taxons:":
                    try:
                        # Some webpages have present in taxons while other have present in taxon (s vs. no s)
                        column = "Present in taxon:"
                        value = get_additional_info(column, soup)
                    except AttributeError:
                        if verbose:
                            logging.debug(
                                f"No values for ELM ID: {elm_id} for {column_ignored_colon}"
                            )

                else:
                    if verbose:
                        logging.debug(
                            f"No values for ELM ID: {elm_id} for {column_ignored_colon}"
                        )

            if not pd.isna(value):
                # Clean up results and add to corresponding position in new dataframe
                value = value.strip().replace("\n", " ").replace("\t", " ")

            df_2.loc[elm_id, column_ignored_colon] = value

        if not uniprot:
            # Get motifs associated with each elm id in original sequence
            start = df.iloc[elm_id_index]["start"]
            stop = df.iloc[elm_id_index]["stop"]
            # numpy.int64 is not Python int, therefore needing additional np.integer
            if isinstance(start, (int, np.integer)) & isinstance(
                stop, (int, np.integer)
            ):
                df_2.loc[elm_id, "Motif in original sequence"] = sequence[
                    start - 1 : stop
                ]
            else:
                df_2.loc[elm_id, "Motif in original sequence"] = np.nan

    # Merge two dataframes and sort by pattern probability
    df_merge = df_2.merge(df, on="elm_identifier", how="right")
    df_merge = df_merge.sort_values(by="Pattern Probability", ascending=False)

    if json:
        results_dict = json_package.loads(df_merge.to_json(orient="records"))

        if save:
            with open("gget_elm_results.json", "w", encoding="utf-8") as f:
                json_package.dump(results_dict, f, ensure_ascii=False, indent=4)

        return results_dict

    else:
        if save:
            df_merge.to_csv("gget_elm_results.csv", index=False)

        return df_merge
