#########################################################
# Todo:
##  
# Lag trekningsliste i Excel for forrige uke hver gang man starter på ny uke
#   * Nummerer aktivitetene som er mer enn 900 sekunder pr medlem
#   * Gi alle aktiviteter med nummer>1 og <5 random nummer, laveste vinner (Manuell sjekk om en aktivitet har fått 2 pga navnebror)
#   * Luke ut de som ikke jobber i Atea Norge
## 
# Identifiser og flagg uvanlige aktiviteter pr type
#  * Mangler Crop
#  * Fjern aktiviteter som er fjernet fra activities, om det finnes en annen med samme bruker+dato + type/navn
## 
#  * les fra alle tokens (Alle må følge ASA)
#  * Legge inn info om hvem som har lest aktiviteten.
#  * Sjekk om noen har id som ikke andre har.
## 
# Sjekk mot medlemslisten hvem som har like navn hver mandag
# Lag fil med run-statistics
#   Lag oversikt over antall medlemmer i klubben
#   Hvor mange aktiviteter som var nye side sist
#########################################################

import requests
import pandas as pd
import json
import errno
from datetime import datetime
from datetime import timedelta
import urllib3
import os
from stat import S_IREAD, S_IRGRP, S_IROTH

# Disable warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Get access token based on client_id, client_secret and refresh_token
def authenticate(client_id, client_secret, refresh_token):
    url = "https://www.strava.com/oauth/token"

    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': "refresh_token",
        'f':'json'
        }

    return requests.post(url, data=data, verify=False).json()['access_token']

# Create activities for admin user - placeholder for date at the end of each day
def create_date_activities(access_token,access_token_write):
    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    header = {'Authorization': 'Bearer ' + access_token}
    param  = {'per_page': 10, 'page': 1}
    response = requests.get(activities_url,headers=header, params=param)
    data = response.json()        

    # Set found_date 7 days back
    found_date = datetime.now()- timedelta(days=7)
    found_date = found_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # Find last date registered in Strava
    for line in data :
        taglist = line['name'].split("#")
        if len(taglist)==2:
            if taglist[1] == "AteaClubStats_Date":
                found_date = datetime.strptime(taglist[0], "%Y-%m-%d")
                break
    # Set newest_date to yesterday @ 23:59 (The last date to write)
    newest_date = datetime.now() - timedelta(days=1)
    newest_date = newest_date.replace(hour=23, minute=59, second=0, microsecond=0)

    # Set write_date to next date to write
    write_date = found_date + timedelta(days=1, hours=23, minutes=59)
    
    url = "https://www.strava.com/api/v3/activities"
    header = {'Authorization': 'Bearer ' + access_token_write}

    # Loop to create all date-activities       
    while newest_date >= write_date:
        activity_name = '%s#AteaClubStats_Date' % write_date.strftime("%Y-%m-%d")
        strava_date = write_date.strftime("%Y-%m-%dT23:59") # ISO 8601 formatted date time

        data = {
            'name': activity_name,
            'type': "run",
            'start_date_local': strava_date,
            'elapsed_time': 1,
            'distance': 0
            }
        
        # Create the placeholder-activity
        response = requests.post(url=url, headers=header, data=data)
        
        # Increase the date with 1 day
        write_date = write_date + timedelta(days=1)

# Read dataframe from Excel. Create file if it doesn't exist
def read_df_from_excel(file_name,df):
    try:
        df = pd.read_excel(file_name)
    except OSError as e:
        if e.errno == errno.ENOENT: # No such file or directory, create new file
            df.to_excel(file_name, index=False)
        else:
            raise
    return df

# Write dataframe to Excel. Change name if error
def write_df_to_excel(file_name,df):
    try:
        df.to_excel('%s' % file_name, index=False)
    except OSError as e:
        if e.errno == errno.EACCES: # Permission denied: File already open
            file_name2 = '%s %s.xlsx' % (file_name, datetime.now().strftime("%Y.%m.%d %H%M"))
            df.to_excel(file_name2, index=False)
            print('Permission denied when saving file. File saved as: "%s". Please rename to "%s"' % (file_name2, file_name))
        else:
            raise


# Get all new activities from Strava API
def get_new_activities_from_strava(access_token,club_id,activities):
    loop = True

    readpage = 1
    pagesize = 50
    url = "https://www.strava.com/api/v3/clubs/%s/activities" % club_id
    counter = 0
    activity_date = datetime.now()
    
    while loop:
        header = {'Authorization': 'Bearer ' + access_token}
        param  = {'per_page': pagesize, 'page': readpage}
        response = requests.get(url, headers=header, params=param )
        data = response.json()

        readpage = readpage + 1
      
        for line in data :
            # There are no date in the data, so manual activities are created as placeholders, date will change when these activites are found
            taglist = line['name'].split("#")
            if len(taglist)==2:
                if taglist[1] == "AteaClubStats_Date":
                    activity_date = datetime.strptime(taglist[0], "%Y-%m-%d")
                    continue
                
            # Assign values to dataframe
            activities.at[counter, 'Athlete']  = line['athlete']['firstname'] +"#"+ line['athlete']['lastname']
            activities.at[counter, 'Name']     = line['name']
            activities.at[counter, 'Type']     = line['type']
            activities.at[counter, 'Duration'] = line['elapsed_time']
            activities.at[counter, 'Distance'] = line['distance']
            activities.at[counter, 'Date']     = activity_date.replace(hour=0, minute=0, second=0, microsecond=0)
            activities.at[counter, 'id']       = "%s#%s#%s#%s" % ( activities.at[counter, 'Athlete'], 
                                                                   activities.at[counter, 'Duration'], 
                                                                   activities.at[counter, 'Distance'],
                                                                   activity_date.strftime("%Y-%m-%d"))

            counter = counter + 1
        
        if len(data)<pagesize :
            loop = False
    
    return activities

# Check "old" activites, replace when the same activity exist in "new" list. Append all that does not exist.
def remove_duplicate_activities(stored_activities,new_activities):
    # Append new activities backwards and reset index
    stored_activities = stored_activities.append(new_activities.iloc[::-1])
    stored_activities.drop_duplicates(subset=['id'], keep='last', inplace=True, ignore_index=True)

    return stored_activities

def main():
    # Set start time for run statistics
    start_time = datetime.now()

    # Read config.json file
    with open("config.json", "r") as jsonfile:
        config = json.load(jsonfile)

    # Get an access token to authenticate when getting data from Strava
    access_token = authenticate(config["clients"][0]["client_id"],config["clients"][0]["client_secret"],config["clients"][0]["refresh_token"])

    # Get an access token to authenticate when writing data to Strava
    access_token_write = authenticate(config["clients"][0]["client_id"],config["clients"][0]["client_secret"],config["clients"][0]["refresh_token_write"])

    #Create manual activities to determine date on activity
    create_date_activities(access_token,access_token_write) 

    # Define data columns
    data_columns = [ "Athlete", "Name", "Type", "Duration", "Distance", "Date", "id" ]
    
    # Get stored data
    data_file_name = 'ClubData %s.xlsx' % config["club_id"]
    stored_activities = pd.DataFrame(columns=data_columns)
    stored_activities = read_df_from_excel(data_file_name, stored_activities)
    print("Stored activities: %i" % len(stored_activities))

    # Get data from Strava
    api_activities = pd.DataFrame(columns=data_columns)
    api_activities = get_new_activities_from_strava(access_token, config["club_id"], api_activities)
    api_activities.set_index('id')
    print("Api activities:    %i" % len(api_activities))

    # Add the new activites to the data already stored, but skip existing activities
    all_activities = pd.DataFrame(columns=data_columns)
    all_activities = remove_duplicate_activities(stored_activities, api_activities)
    print("All activities:    %i, %i added" % (len(all_activities), len(all_activities)-len(stored_activities)))

    # Debug: Write the new activities to an Excel file
    file_name = 'ClubData %s.xlsx' % datetime.now().strftime("%Y.%m.%d %H%M")
    all_activities.to_excel(file_name, index=False)
    write_df_to_excel('TestData.xlsx', stored_activities)

    # Write the dataset to file
    write_df_to_excel(data_file_name, all_activities)
    
    # Write a copy to TP2B
    strava_data_file = 'C:/Users/ChrVage/Atea/NO-ATEA alle - Strava Data/StravaData.xlsx'
    write_df_to_excel(strava_data_file, all_activities)
    # os.chmod(strava_data_file, S_IREAD|S_IRGRP|S_IROTH)

    # Write run statistics
    run_statistics = pd.read_excel("RunStats.xlsx")
    stat_columns = [ "Timestamp", 
                     "Execution time (sec)", 
                     "Since last run (hrs)", 
                     "Stored activities", 
                     "API activities", 
                     "Appended", 
                     "Appended/New" ]
    data = [ datetime.now(), 
             (datetime.now() - start_time).total_seconds(), 
             (datetime.now() - run_statistics['Timestamp'].iloc[-1])*24, 
             len(stored_activities), 
             len(api_activities), 
             len(all_activities)-len(stored_activities), 
             (len(all_activities)-len(stored_activities))//len(api_activities)]
    this_run = pd.DataFrame([data], columns=stat_columns )
    run_statistics = run_statistics.append(this_run, ignore_index=True )
    write_df_to_excel('RunStats.xlsx', run_statistics)

# Run the main() function only when this file is called as main.
if __name__ == "__main__":
    main()