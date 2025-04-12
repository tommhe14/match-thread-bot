#!/usr/bin/python
# -*- coding: utf-8 -*-

import praw,urllib,http.cookiejar,re,logging,logging.handlers,datetime,requests,requests.auth,sys,json,unicodedata
from praw.models import Message
from collections import Counter
from itertools import groupby
from time import sleep

# TO DO: 
# cookielib to http.cookiejar
# deal with incorrect matching of non-existent game (eg using "City", etc) - ie better way of finding matches (nearest neighbour?)
# more robust handling of errors

# every minute, check mail, create new threads, update all current threads

# browser header (to avoid 405 error)
hdr = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11',
   'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
   'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
   'Accept-Encoding': 'none',
   'Accept-Language': 'en-US,en;q=0.8',
   'Connection': 'keep-alive'}

activeThreads = []
notify = False
messaging = True
spriteSubs = ['soccer','Gunners','fcbayern','soccerdev2','mls']
DSTtimedelta = 4

# naughty list				
usrblacklist = ['dbawbaby',
				'12F12',
				'KYAmiibro']
				
# allowed to make multiple threads
usrwhitelist = ['spawnofyanni',
				'Omar_Til_Death',
				'x69-',
				'overscore_']
				
# allowed to post early threads in given subreddit
timewhitelist = {'matchthreaddertest': ['spawnofyanni'],
				 'ussoccer': ['redravens'],
				 'coyssandbox': ['wardamnspurs'],
				 'rsca': ['ghustbe'],
				 'brightonhovealbion': ['discombobulated_pen']}

# adjust time limit in given subreddit				 
custTimeLimit = {'coyh': [30],
				 'fccincinnati': [35],
				 'soccer': [20],
				 'indianfootball': [60],
				 'canadasoccer': [30],
				 'themariners': [60],
				 'brightonhovealbion': [1440],
				 'chelseafc': [60],
				 'coyh': [60],
				 'mls': [15]}
				 
# subreddit needs link flair
needsflairlist = {'soccer': 8,
				  'matchthreaddertest': 1,
				  'santosfc': 0,
				  'futebol': 6,
				  'fobaluru': 8,
				  'chelseafc': 25,
				  'brightonhovealbion': 11,
				  'themariners': 21,
				  'panathinaikos': 1,
				  'primeiraliga': 0}

# markup constants
goal=0;pgoal=1;ogoal=2;mpen=3;yel=4;syel=5;red=6;subst=7;subo=8;subi=9;strms=10;lines=11;evnts=12

def getTimestamp():
        dt = str(datetime.datetime.now().month) + '/' + str(datetime.datetime.now().day) + ' '
        hr = str(datetime.datetime.now().hour) if len(str(datetime.datetime.now().hour)) > 1 else '0' + str(datetime.datetime.now().hour)
        min = str(datetime.datetime.now().minute) if len(str(datetime.datetime.now().minute)) > 1 else '0' + str(datetime.datetime.now().minute)
        t = '[' + hr + ':' + min + '] '
        return dt + t

def setup():
        try:
                f = open('login.txt')
                line = f.readline()
                admin,username,password,subreddit,user_agent,id,secret,redirect = line.split('||',8)
                f.close()
                r = praw.Reddit(client_id=id, client_secret=secret, username=username, password=password, user_agent=user_agent)
                r.validate_on_submit = True
                return r,admin,username,password,subreddit,user_agent,id,secret,redirect
        except:
                print(getTimestamp() + "Setup error: please ensure 'login.txt' file exists in its correct form (check readme for more info)\n")
                logger.exception("[SETUP ERROR:]")
                sleep(10)

	
# save activeThreads
def saveData():
	f = open('active_threads.txt', 'w+')
	s = ''
	for data in activeThreads:
		matchID,t1,t2,thread_id,reqr,sub,type = data
		s += matchID + '####' + t1 + '####' + t2 + '####' + thread_id + '####' + reqr + '####' + sub + '####' + type + '&&&&'
	s = s[0:-4] # take off last &&&&
	f.write(s)
	f.close()

# read saved activeThreads data	
def readData():
	f = open('active_threads.txt', 'a+')
	f.seek(0)
	s = f.read()
	info = s.split('&&&&')
	if info[0] != '':
		
		for d in info:
			[matchID,t1,t2,thread_id,reqr,sub,type] = d.split('####')
			data = matchID, t1, t2, thread_id, reqr, sub, type
			activeThreads.append(data)
			logger.info("Active threads: %i - added %s vs %s (/r/%s)", len(activeThreads), t1, t2, sub)
			print(getTimestamp() + "Active threads: " + str(len(activeThreads)) + " - added " + t1 + " vs " + t2 + " (/r/" + sub + ")")
	f.close()
	
def resetAll():
	logger.info("[RESET ALL]")
	print(getTimestamp() + "Resetting all threads...")
	removeList = list(activeThreads)
	for data in removeList:
		activeThreads.remove(data)
		logger.info("Active threads: %i - removed %s vs %s (/r/%s)", len(activeThreads), data[1], data[2], data[5])
		print(getTimestamp() + "Active threads: " + str(len(activeThreads)) + " - removed " + data[1] + " vs " + data[2] + " (/r/" + data[5] + ")")
		saveData()
	print("complete.")
		
def flushMsgs():
	logger.info("[FLUSH MSGS]")
	print(getTimestamp() + "Flushing messages...")
	for msg in r.inbox.unread(limit=None):
		msg.mark_read()
	print("complete.")

def loadMarkup(subreddit):
	try:
		markup = [line.rstrip('\n') for line in open(subreddit + '.txt')]
	except:
		markup = [line.rstrip('\n') for line in open('mane-test.txt')]
	return markup
	
def getBotStatus():
	thread = r.submission('22ah8i')
	status = re.findall('bar-10-(.*?)\)',thread.selftext)
	msg = re.findall('\| \*(.*?)\*',thread.selftext)
	return status[0],msg[0]
	
# get current match time/status
def getStatus(matchID):
    venue, ko_day, ko_time, status, comp = getMatchSummary(matchID)

    if status:  
        return status
    else:
        return 'v' 
	
def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)])
	
def guessRightMatch(possibles):
	matchOn = []
	for matchID in possibles:
		status = getStatus(matchID)
		if len(status) > 0:
			matchOn.append(status[0].isdigit())
		else:
			matchOn.append(False)
	stati_int = [int(elem) for elem in matchOn]
	if sum(stati_int) == 1:
		guess = possibles[stati_int.index(1)]
	else:
		guess = possibles[0]
	return guess

def fetch_espn_scoreboard():
    url = "https://site.web.api.espn.com/apis/v2/scoreboard/header?region=gb&lang=en&contentorigin=espn&buyWindow=1m&showAirings=buy,live,replay&showZipLookup=true&tz=Europe/London&_ceID=15878776"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch data. Status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error during the request: {e}")
        return None
	
def findMatchSite(team1, team2):
    print(getTimestamp() + "Finding ESPN match for " + team1 + " vs " + team2 + "...", end='')
    starttime = datetime.datetime.now()

    try:
        data = fetch_espn_scoreboard()
        if not data:
            return 'no match'

        # Normalize the input team names to lowercase
        t1 = team1.lower()
        t2 = team2.lower()

        linkList = []
        for sport in data.get("sports", []):
            for league in sport.get("leagues", []):
                for event in league.get("events", []):
                    home_team = event["competitors"][0]["displayName"].lower()
                    away_team = event["competitors"][1]["displayName"].lower()
                    match_id = event["id"]

                    # Check if the provided team1 name exists in home or away teams
                    if (t1.lower().strip() in home_team.lower() or t1.lower().strip() in away_team.lower()) and (t2.lower().strip() in home_team.lower() or t2.lower().strip() in away_team.lower()):
                        linkList.append(match_id)
                        print(f"Match found and appended: {home_team} vs {away_team} (ID: {match_id})")

        # If matches are found, get the most common match ID
        if linkList:
            counts = Counter(linkList)
            most_common_match_id = counts.most_common(1)[0][0]
            endtime = datetime.datetime.now()
            timeelapsed = endtime - starttime
            print(f"complete ({str(timeelapsed.seconds)} seconds)")
            return most_common_match_id
        else:
            endtime = datetime.datetime.now()
            timeelapsed = endtime - starttime
            print(f"complete ({str(timeelapsed.seconds)} seconds)")
            return 'no match'

    except requests.exceptions.Timeout:
        print("ESPN access timeout")
        return 'no match'
	
def getTeamIDs(matchID):
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            match_data = response.json()
            
            events = match_data.get("boxscore", {}).get("form", [])
            if events:
                event = events[0]
                
                home_team_id = event.get("events", [{}])[0].get("homeTeamId", "")
                away_team_id = event.get("events", [{}])[0].get("awayTeamId", "")
                
                return home_team_id, away_team_id
            else:
                print("Error: No event data available.")
                return '', ''
        else:
            print(f"Failed to fetch match details. Status code: {response.status_code}")
            return '', ''
    except requests.exceptions.RequestException as e:
        print(f"Error during the request: {e}")
        return '', ''
		
def getLineUps(matchID):
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            
            rosters = data.get("rosters", [])
            if len(rosters) < 2:
                print("No rosters data available.")
                return None

            home_roster = rosters[0].get("roster", [])
            away_roster = rosters[1].get("roster", [])

            team1start = []
            team1sub = []
            team2start = []
            team2sub = []

            for player in home_roster:
                player_name = player.get("athlete", {}).get("displayName", "Unknown Player")
                if player.get("starter", False):
                    team1start.append(player_name)
                else:
                    team1sub.append(player_name)

            for player in away_roster:
                player_name = player.get("athlete", {}).get("displayName", "Unknown Player")
                if player.get("starter", False):
                    team2start.append(player_name)
                else:
                    team2sub.append(player_name)

            return team1start, team1sub, team2start, team2sub

        else:
            print(f"Failed to fetch match details. Status code: {response.status_code}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error during the request: {e}")
        return None
		
def getTeamAbbrevs(matchID):
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            match_data = response.json()
            
            form_data = match_data.get("boxscore", {}).get("form", [])
            if len(form_data) >= 2:
                home_team_abbr = form_data[0].get("team", {}).get("abbreviation", "")
                away_team_abbr = form_data[1].get("team", {}).get("abbreviation", "")
                
                return home_team_abbr, away_team_abbr
            else:
                print("Error: Insufficient form data available.")
                return '', ''
        else:
            print(f"Failed to fetch match details. Status code: {response.status_code}")
            return '', ''
    except requests.exceptions.RequestException as e:
        print(f"Error during the request: {e}")
        return '', ''
	
def getTeamNames(matchID):
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            match_data = response.json()
            
            form_data = match_data.get("boxscore", {}).get("form", [])
            if len(form_data) >= 2:
                home_team_name = form_data[0].get("team", {}).get("displayName", "")
                away_team_name = form_data[1].get("team", {}).get("displayName", "")
                
                return home_team_name, away_team_name
            else:
                print("Error: Insufficient form data available.")
                return '', ''
        else:
            print(f"Failed to fetch match details. Status code: {response.status_code}")
            return '', ''
    except requests.exceptions.RequestException as e:
        print(f"Error during the request: {e}")
        return '', ''
	
def getMatchSummary(matchID):
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)


        if response.status_code == 200:
            match_data = response.json()

            venue = match_data.get("gameInfo", {}).get("venue", {}).get("fullName", "")

            header = match_data.get("header", {})
            if header:
                comp = header.get("season", {}).get("name", "")

                match_datetime = header.get("competitions", [{}])[0].get("date", "")
                if match_datetime:
                    match_time = datetime.datetime.strptime(match_datetime, "%Y-%m-%dT%H:%MZ")
                    ko_day = match_time.day
                    ko_time = match_time.strftime("%H:%M")
                else:
                    ko_day, ko_time = "", ""
                
                status = match_data.get("header", {}).get("competitions", {})[0].get("status", {}).get("type", "").get("detail", "")

            return venue, ko_day, ko_time, status, comp

        else:
            print(f"Failed to fetch match details. Status code: {response.status_code}")
            return "", "", "", "", ""

    except requests.exceptions.RequestException as e:
        print(f"Error during the request: {e}")
        return "", "", "", "", ""
	
# get venue, ref, lineups, etc from ESPN	
def getMatchInfo(matchID):
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            match_data = response.json()

            team1Start, team1Sub, team2Start, team2Sub = getLineUps(matchID)
            
            team1fix, team2fix = getTeamNames(matchID)
            t1id, t2id = getTeamIDs(matchID)
            venue, ko_day, ko_time, status, comp = getMatchSummary(matchID)
            t1abb, t2abb = getTeamAbbrevs(matchID)  # Assuming getTeamAbbrevs is defined

            print("complete.")
            return (team1fix, t1id, team2fix, t2id, team1Start, team1Sub, team2Start, team2Sub, venue, ko_day, ko_time, status, comp, t1abb, t2abb)
        else:
            print(f"Failed to fetch match data: {response.status_code}")
            return None  

    except Exception as e:
        print(f"Error fetching match data: {e}")
        return None  

	
def getSprite(teamID,sub):
	try:
		customCrestSubs = ['mls']
		crestFile = 'crests.txt'
		if sub in customCrestSubs:
			crestFile = sub + crestFile
		lines = [line.rstrip('\n') for line in open(crestFile)]
		for line in lines:
			if line != '' and not line.startswith('||'):
				line = line.split('\t')[len(line.split('\t'))-1]
				split = line.split('::')
				EID = split[0]
				sprite = split[1]
				if EID == teamID:
					return sprite
		return ''
	except:
		return ''
	
def writeLineUps(sub,body,t1,t1id,t2,t2id,team1Start,team1Sub,team2Start,team2Sub):
	markup = loadMarkup(sub)
	t1sprite = ''
	t2sprite = ''
	if sub.lower() in spriteSubs and getSprite(t1id,sub) != '' and getSprite(t2id,sub) != '':
		t1sprite = getSprite(t1id,sub) + ' '
		t2sprite = getSprite(t2id,sub) + ' '
	
	body += '**LINE-UPS**\n\n**' + t1sprite + t1 + '**\n\n'
	linestring = ''
	for name in team1Start:
		if '!sub' in name:
			linestring += ' (' + markup[subst] + name[5:] + ')'
		else:
			linestring += ', ' + name
	linestring = linestring[2:] + '.\n\n'
	body += linestring + '**Subs:** '
	body += ", ".join(x for x in team1Sub) + ".\n\n^____________________________\n\n"
	
	body += '**' + t2sprite + t2 + '**\n\n'
	linestring = ''
	for name in team2Start:
		if '!sub' in name:
			linestring += ' (' + markup[subst] + name[5:] + ')'
		else:
			linestring += ', ' + name
	linestring = linestring[2:] + '.\n\n'
	body += linestring + '**Subs:** '
	body += ", ".join(x for x in team2Sub) + "."
	
	return body

	
def grabEvents(matchID, subreddit):
    markup = loadMarkup(subreddit)
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            match_data = response.json()
            commentary = ""

            for event in match_data.get('commentary', []):
                event_type = event.get('play', {}).get('type', {}).get('text', '').lower()

                important_event_types = [
                    "goal", "penalty scored", "own goal", "yellow card", "red card", "substitution"
                ]

                if event_type in important_event_types:
                    time = event.get('time', {}).get('displayValue', '')
                    description = event.get('text', '')

                    info = f"**{time}** "

                    if event_type == "goal":
                        info += markup[0] + ' **' + description + '**'
                    elif event_type == "penalty scored":
                        info += markup[1] + ' **' + description + '**'
                    elif event_type == "own goal":
                        info += markup[2] + ' **' + description + '**'
                    elif event_type == "yellow card":
                        info += markup[4] + ' ' + description
                    elif event_type == "red card":
                        info += markup[6] + ' ' + description
                    elif event_type == "substitution":
                        info += markup[7] + ' ' + description

                    commentary += info + '\n\n'

            print("Complete.")
            return commentary
        else:
            print("Failed to fetch commentary.")
            return ""

    except Exception as e:
        print("Error fetching events:")
        return ""

def getTimes(ko):
	hour = ko[0:ko.index(':')]
	minute = ko[ko.index(':')+1:ko.index(':')+3]
	hour_i = int(hour)
	min_i = int(minute)
	
	now = datetime.datetime.now()
	return (hour_i,min_i,now)
	
# attempt submission to subreddit
def submitThread(sub,title):
	print(getTimestamp() + "Submitting " + title + "...", end='')
	try:
		if sub in needsflairlist:
			thread = r.subreddit(sub).submit(title,selftext='**Venue:**\n\n**LINE-UPS**',send_replies=False,flair_id=list(r.subreddit(sub).flair.link_templates)[needsflairlist[sub]]['id'])
			thread.validate_on_submit = True
		else:
			thread = r.subreddit(sub).submit(title,selftext='**Venue:**\n\n**LINE-UPS**',send_replies=False)
		print("complete.")
		print(getTimestamp() + thread.shortlink)
		return True,thread
	except:
		print("failed.")
		logger.exception("[SUBMIT ERROR:]")
		return False,''
	
# create a new thread using provided teams	
def createNewThread(team1,team2,reqr,sub,direct,type):	
	if direct == '':
		matchID = findMatchSite(team1,team2)
	else:
		matchID = direct
	if matchID != 'no match':
		gotinfo = False
		while not gotinfo:
			try:
				t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub, venue, ko_day, ko_time, status, comp, t1abb, t2abb = getMatchInfo(matchID)
				gotinfo = True
			except requests.exceptions.Timeout:
				print(getTimestamp() + "ESPNFC access timeout for " + team1 + " vs " + team2)
		
		botstat,statmsg = getBotStatus()
		# don't make a post if there's some fatal error
		if botstat == 'red':
			print(getTimestamp() + "Denied " + t1 + " vs " + t2 + " request for - status set to red")
			logger.info("Denied %s vs %s request - status set to red", t1, t2)
			return 8,''
				
		# don't post if user is blacklisted
		if reqr in usrblacklist:
			print(getTimestamp() + "Denied post request from /u/" + reqr + " - blacklisted")
			logger.info("Denied post request from %s - blacklisted", reqr)
			return 9,''
		
		# don't create a thread if the bot already made it or if user already has an active thread
		for d in activeThreads:
			matchID_at,t1_at,t2_at,id_at,reqr_at,sub_at,type_at = d
			if t1 == t1_at and sub == sub_at and type == type_at:
				print(getTimestamp() + "Denied " + t1 + " vs " + t2 + " request for /r/" + sub + " - thread already exists")
				logger.info("Denied %s vs %s request for %s - thread already exists", t1, t2, sub)
				return 4,id_at
			if reqr == reqr_at and reqr not in usrwhitelist:
				print(getTimestamp() + "Denied post request from /u/" + reqr + " - has an active thread request")
				logger.info("Denied post request from %s - has an active thread request", reqr)
				return 7,''
		
		# don't create a thread if the match is done (probably found the wrong match)
		if reqr != admin:
			if status.startswith('FT') or status == 'AET':
				print(getTimestamp() + "Denied " + t1 + " vs " + t2 + " request - match appears to be finished")
				logger.info("Denied %s vs %s request - match appears to be finished", t1, t2)
				return 3,''
		
		timelimit = 5
		if sub.lower() in custTimeLimit:
			timelimit = custTimeLimit[sub.lower()][0]
		# don't create a thread more than 5 minutes before kickoff
		if sub.lower() not in timewhitelist or sub.lower() in timewhitelist and reqr.lower() not in timewhitelist[sub.lower()]:
			hour_i, min_i, now = getTimes(ko_time)
			now_f = now + datetime.timedelta(hours = DSTtimedelta, minutes = timelimit)
			print(now_f.day)
			if ko_day == '':
				return 1,''
			if now_f.day < int(ko_day):
				print(getTimestamp() + "Denied " + t1 + " vs " + t2 + " request - more than " + timelimit + " minutes to kickoff")
				logger.info("Denied %s vs %s request - more than 5 minutes to kickoff (day check failed)", t1, t2)
				return 2,''
			if (now_f.day == int(ko_day)) and (now_f.hour < hour_i):
				print(getTimestamp() + "Denied " + t1 + " vs " + t2 + " request - more than " + timelimit + " minutes to kickoff")
				#print(str(now_f.hour) + ' vs ' + str(hour_i))
				logger.info("Denied %s vs %s request - more than 5 minutes to kickoff (hour check failed)", t1, t2)
				return 2,''
			if (now_f.hour == hour_i) and (now_f.minute < min_i):
				print(getTimestamp() + "Denied " + t1 + " vs " + t2 + " request - more than " + timelimit + " minutes to kickoff")
				logger.info("Denied %s vs %s request - more than 5 minutes to kickoff (minute check failed)", t1, t2)
				return 2,''

		title = ''
		if type == 'srs':
			title += 'Serious '
		title += 'Match Thread: ' + t1 + ' vs ' + t2
		if (sub in ['matchthreaddertest','soccerdev2']):
			title = title + ' [' + t1abb + '-' + t2abb + ']'
		if comp != '':
			title = title + ' | ' + comp
		result,thread = submitThread(sub,title)
		
		# if subreddit was invalid, notify
		if result == False:
			return 5,''
		
		short = thread.shortlink
		id = short[short.index('.it/')+4:]
		redditstream = 'http://www.reddit-stream.com/comments/' + id 
		
		data = matchID, t1, t2, id, reqr, sub, type
		activeThreads.append(data)
		saveData()
		print(getTimestamp() + "Active threads: " + str(len(activeThreads)) + " - added " + t1 + " vs " + t2 + " (/r/" + sub + ")")
		logger.info("Active threads: %i - added %s vs %s (/r/%s)", len(activeThreads), t1, t2, sub)
		
		if status == 'v':
			status = "0'"
			
		markup = loadMarkup(sub)
		
		if sub.lower() in spriteSubs:
			t1sprite = ''
			t2sprite = ''
			if getSprite(t1id,sub) != '' and getSprite(t2id,sub) != '':
				t1sprite = getSprite(t1id,sub)
				t2sprite = getSprite(t2id,sub)
			textbody = '#**' + status + ': ' + t1 + ' ' + t1sprite + ' [vs](#bar-3-white) ' + t2sprite + ' ' + t2 + '**\n\n'

		else:
			textbody = '#**' + status + ": " + t1 + ' vs ' + t2 + '**\n\n'

		textbody += '**Venue:** ' + venue + '\n\n'
		textbody += '[Auto-refreshing reddit comments link](' + redditstream + ')\n\n---------\n\n'

		textbody += markup[lines] + ' ' 
		textbody = writeLineUps(sub,textbody,t1,t1id,t2,t2id,team1Start,team1Sub,team2Start,team2Sub)
		
		#[^[Request ^a ^match ^thread]](http://www.reddit.com/message/compose/?to=MatchThreadder&subject=Match%20Thread&message=Team%20vs%20Team) ^| [^[Request ^a ^thread ^template]](http://www.reddit.com/message/compose/?to=MatchThreadder&subject=Match%20Info&message=Team%20vs%20Team) ^| [^[Current ^status ^/ ^bot ^info]](http://www.reddit.com/r/soccer/comments/22ah8i/introducing_matchthreadder_a_bot_to_set_up_match/)"
		
		textbody += '\n\n------------\n\n' + markup[evnts] + ' **MATCH EVENTS** | *via [ESPN](http://www.espn.com/soccer/match?gameId=' + matchID + ')*\n\n'
		textbody += "\n\n--------\n\n*^(Don't see a thread for a match you're watching?) [^(Click here)](https://www.reddit.com/r/soccer/wiki/matchthreads#wiki_match_thread_bot) ^(to learn how to request a match thread from this bot.)*"

		
		if botstat != 'green':
			textbody += '*' + statmsg + '*\n\n'
		
		thread.edit(textbody)
		sleep(5)

		return 0,id
	else:
		print(getTimestamp() + "Could not find match info for " + team1 + " vs " + team2)
		logger.info("Could not find match info for %s vs %s", team1, team2)
		return 1,''

# if the requester just wants a template		
def createMatchInfo(team1, team2):
    matchID = findMatchSite(team1, team2)
    if matchID != 'no match':
        t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub, venue, ko_day, ko_time, status, comp, t1abb, t2abb = getMatchInfo(matchID)
        
        markup = loadMarkup('soccer')
        score = getScore(matchID)

        # Use "vs" if the match hasn't started yet
        scoreStr = "vs" if " at " in status else score

        body = f'#**{status}: {t1} {scoreStr} {t2}**\n\n'
        body += f'**Venue:** {venue}\n\n--------\n\n'
        body += markup[lines] + ' '
        body = writeLineUps('soccer', body, t1, t1id, t2, t2id, team1Start, team1Sub, team2Start, team2Sub)
        
        events = grabEvents(matchID, "mane-test")
        body += '\n\n------------\n\n' + markup[evnts] + ' **MATCH EVENTS**\n\n' + events
        
        logger.info("Provided info for %s vs %s", t1, t2)
        print(getTimestamp() + "Provided info for " + t1 + " vs " + t2)
        return 0, body
    else:
        return 1, ''



# delete a thread (on admin request)
def deleteThread(id):
	try:
		if '//' in id:
			id = re.findall('comments/(.*?)/',id)[0]
		thread = r.submission(id)
		for data in activeThreads:
			matchID,team1,team2,thread_id,reqr,sub,type = data
			if thread_id == id:
				thread.delete()
				activeThreads.remove(data)
				logger.info("Active threads: %i - removed %s vs %s (/r/%s)", len(activeThreads), team1, team2, sub)
				print(getTimestamp() + "Active threads: " + str(len(activeThreads)) + " - removed " + team1 + " vs " + team2 + " (/r/" + sub + ")")
				saveData()
				return team1 + ' vs ' + team2
		return ''
	except:
		return ''
		
# remove incorrectly made thread if requester asks within 5 minutes of creation
def removeWrongThread(id,req):
	try:
		thread = r.submission(id)
		dif = datetime.datetime.utcnow() - datetime.datetime.utcfromtimestamp(thread.created_utc)
		for data in activeThreads:
			matchID,team1,team2,thread_id,reqr,sub,type = data
			if thread_id == id:
				if reqr != req:
					return 'req'
				if dif.days != 0 or dif.seconds > 300:
					return 'time'
				thread.delete()
				activeThreads.remove(data)
				logger.info("Active threads: %i - removed %s vs %s (/r/%s)", len(activeThreads), team1, team2, sub)
				print(getTimestamp() + "Active threads: " + str(len(activeThreads)) + " - removed " + team1 + " vs " + team2 + " (/r/" + sub + ")")
				saveData()
				return team1 + ' vs ' + team2
		return 'thread'
	except:
		return 'thread'
		
# default attempt to find teams: split input in half, left vs right	
def firstTryTeams(msg):
	t = msg.split()
	spl = int(len(t)/2)
	t1 = t[0:spl]
	t2 = t[spl+1:]
	t1s = ''
	t2s = ''
	for word in t1:
		t1s += word + ' '
	for word in t2:
		t2s += word + ' '
	return [t1s,t2s]

def getScore(matchID):
    try:
        url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        match_data = response.json()

        boxscore = match_data.get("header", {}).get("competitions", [])[0]
        home_score = boxscore["competitors"][0]["score"]
        away_score = boxscore["competitors"][1]["score"]
        score = f"{home_score}-{away_score}"
        return score
    except Exception as e:
        print(e)
        return None

# check for new mail, create new threads if needed
def checkAndCreate():
	detour = False
	replytext = "Update from /u/spawnofyanni, June 15:\n\nHi there. I'm currently redirecting all DMs sent to /u/matchthreadder to this automated message. ESPN seems to have gone through a major backend redesign, which means that all of the code that runs this bot was just made obsolete. I'm going to spend a little time figuring out how bad this problem is, and will post an update on what this means as soon as I can. In the mean time, I'd recommend making a thread manually."
	if len(activeThreads) > 0:		
		print(getTimestamp() + "Checking messages...")
	delims = [' x ',' - ',' v ',' vs ']
	#unread_messages = []
	subdel = ' for '
	for msg in r.inbox.unread(limit=None):
		msg.mark_read()
		print(msg)
		#	unread_messages.append(msg)
		sub = subreddit
		if msg.subject.lower() == 'mtdirect':
			if detour and msg.author.name != admin:
				#replytext = '/u/MatchThreadder is down for maintenance (starting Dec 5). The bot should be back up in a few days. Keep an eye out for when it starts posting threads again - message /u/spawnofyanni if you have any questions!\n\n--------------\n\n[Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you want to know how to make your own match thread.'
				msg.reply(body=replytext)
			else:
				subreq = msg.body.split(subdel,2)
				if subreq[0] != msg.body:
					sub = subreq[1].split('/')[-1]
					sub = sub.lower()
					sub = sub.strip()
				threadStatus,thread_id = createNewThread('','',msg.author.name,sub,subreq[0],'reg')
				if messaging:
					replytext = ""
					if threadStatus == 0: # thread created successfully
						replytext = "[Here](http://www.reddit.com/r/" + sub + "/comments/" + thread_id + ") is a link to the thread you've requested. Thanks for using this bot!\n\n-------------------------\n\n*Did I create a thread for the wrong match? [Click here and press send](http://www.reddit.com/message/compose/?to=" + username + "&subject=delete&message=" + thread_id + ") to delete the thread (note: this will only work within five minutes of the thread's creation). This probably means that I can't find the right match - sorry!*"
					if threadStatus == 1: # not found
						replytext = "Sorry, I couldn't find info for that match. If the match you requested appears on [this page](http://www.espn.com/soccer/scores), please let /u/spawnofyanni know about this error.\n\n-------------------------\n\n*Why not run your own match thread? [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you're not sure how.*\n\n*You could also check out these match thread creation tools from /u/afito and /u/Mamu7490:*\n\n*[RES Templates](https://www.reddit.com/r/soccer/comments/3ndd7b/matchthreads_for_beginners_the_easy_way/)*\n\n*[MTmate](https://www.reddit.com/r/soccer/comments/3huyut/release_v09_of_mtmate_matchthread_generator/)*"
					if threadStatus == 2: # before kickoff
						replytext = "Please wait until at least 5 minutes to kickoff to send me a thread request, just in case someone does end up making one themselves. Thanks!\n\n-------------------------\n\n*Why not run your own match thread? [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you're not sure how.*\n\n*You could also check out these match thread creation tools from /u/afito and /u/Mamu7490:*\n\n*[RES Templates](https://www.reddit.com/r/soccer/comments/3ndd7b/matchthreads_for_beginners_the_easy_way/)*\n\n*[MTmate](https://www.reddit.com/r/soccer/comments/3huyut/release_v09_of_mtmate_matchthread_generator/)*"
					if threadStatus == 3: # after full time - probably found the wrong match
						replytext = "Sorry, I couldn't find a currently live match with those teams - are you sure the match has started (and hasn't finished)? If you think this is a mistake, it probably means I can't find that match.\n\n-------------------------\n\n*Why not run your own match thread? [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you're not sure how.*\n\n*You could also check out these match thread creation tools from /u/afito and /u/Mamu7490:*\n\n*[RES Templates](https://www.reddit.com/r/soccer/comments/3ndd7b/matchthreads_for_beginners_the_easy_way/)*\n\n*[MTmate](https://www.reddit.com/r/soccer/comments/3huyut/release_v09_of_mtmate_matchthread_generator/)*"
					if threadStatus == 4: # thread already exists
						replytext = "There is already a [match thread](http://www.reddit.com/r/" + sub + "/comments/" + thread_id + ") for that game. Join the discussion there!"
					if threadStatus == 5: # invalid subreddit
						replytext = "Sorry, I couldn't post to /r/" + sub + ". It may not exist, or I may have hit a posting limit."
					if threadStatus == 6: # sub blacklisted
						replytext = "Sorry, I can't post to /r/" + sub + ". Please message /u/" + admin + " if you think this is a mistake."
					msg.reply(body=replytext)
					
		if msg.subject.lower() == 'match thread' or msg.subject.lower() == 'serious match thread':
			type = 'reg'
			if msg.subject.lower() == 'serious match thread':
				type = 'srs'
			if detour and msg.author.name != admin:
				#replytext = '/u/MatchThreadder is down for maintenance (starting Dec 5). The bot should be back up in a few days. Keep an eye out for when it starts posting threads again - message /u/spawnofyanni if you have any questions!\n\n--------------\n\n[Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you want to know how to make your own match thread.'
				msg.reply(body=replytext)
			else:
				subreq = msg.body.split(subdel,2)
				if subreq[0] != msg.body:
					sub = subreq[1].split('/')[-1]
					sub = sub.lower()
					sub = sub.strip()
					print(sub)
				if subreq[0].strip().isdigit():
					threadStatus,thread_id = createNewThread('','',msg.author.name,sub,subreq[0].strip(),type)
				else:
					teams = firstTryTeams(subreq[0].strip())
					for delim in delims:
						attempt = subreq[0].split(delim,2)
						if attempt[0] != subreq[0]:
							teams = attempt
					threadStatus,thread_id = createNewThread(teams[0],teams[1],msg.author.name,sub,'',type)
				if messaging:
					replytext = ""
					if threadStatus == 0: # thread created successfully
						replytext = "[Here](http://www.reddit.com/r/" + sub + "/comments/" + thread_id + ") is a link to the thread you've requested. Thanks for using this bot!\n\n-------------------------\n\n*Did I create a thread for the wrong match? [Click here and press send](http://www.reddit.com/message/compose/?to=" + username + "&subject=delete&message=" + thread_id + ") to delete the thread (note: this will only work within five minutes of the thread's creation). This probably means that I can't find the right match - sorry!*"
						if notify:
							r.send_message(admin,"Match thread request fulfilled","/u/" + msg.author.name + " requested " + teams[0] + " vs " + teams[1] + " in /r/" + sub + ". \n\n[Thread link](http://www.reddit.com/r/" + sub + "/comments/" + thread_id + ") | [Deletion link](http://www.reddit.com/message/compose/?to=" + username + "&subject=delete&message=" + thread_id + ")")
					if threadStatus == 1: # not found
						replytext = "Sorry, I couldn't find info for that match. If the match you requested appears on [this page](http://www.espn.com/soccer/scores), please let /u/spawnofyanni know about this error.\n\n-------------------------\n\n*Note: Have you tried requesting this thread using the [ESPN match ID](https://i.imgur.com/qNkrV5W.png)? This method of requesting threads can work better than referencing team names. [Click here](https://www.reddit.com/r/soccer/comments/bd30gq/matchthreadder_update_a_new_way_to_request_threads/) for more information.*"
					if threadStatus == 2: # before kickoff
						replytext = "Please wait until at least 5 minutes to kickoff to send me a thread request, just in case someone does end up making one themselves. Thanks!\n\n-------------------------\n\n*Why not run your own match thread? [Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you're not sure how.*\n\n*You could also check out these match thread creation tools from /u/afito and /u/Mamu7490:*\n\n*[RES Templates](https://www.reddit.com/r/soccer/comments/3ndd7b/matchthreads_for_beginners_the_easy_way/)*\n\n*[MTmate](https://www.reddit.com/r/soccer/comments/3huyut/release_v09_of_mtmate_matchthread_generator/)*"
					if threadStatus == 3: # after full time - probably found the wrong match
						replytext = "Sorry, I couldn't find a currently live match with those teams - are you sure the match has started (and hasn't finished)?\n\n-------------------------\n\n*Note: If you think this is a mistake, it probably means I can't find that match. Have you tried requesting this thread using the [ESPN match ID](https://i.imgur.com/qNkrV5W.png)? This method of requesting threads can work better than referencing team names. [Click here](https://www.reddit.com/r/soccer/comments/bd30gq/matchthreadder_update_a_new_way_to_request_threads/) for more information.*"
					if threadStatus == 4: # thread already exists
						replytext = "There is already a [match thread](http://www.reddit.com/r/" + sub + "/comments/" + thread_id + ") for that game. Join the discussion there!"
					if threadStatus == 5: # invalid subreddit
						replytext = "Sorry, I couldn't post to /r/" + sub + ". It may not exist, or I may have hit a posting limit."
					if threadStatus == 6: # sub blacklisted
						replytext = "Sorry, I can't post to /r/" + sub + ". Please message /u/" + admin + " if you think this is a mistake."
					if threadStatus == 7: # thread limit
						replytext = "Sorry, you can only have one active thread request at a time."
					if threadStatus == 8: # status set to red
						replytext = "Sorry, the bot is currently unable to post threads. Check with /u/" + admin + " for more info; this should hopefully be resolved soon."
					msg.reply(body=replytext)		
					
		if msg.subject.lower() in ['match info', 'match information']:
			if detour:
				#replytext = '/u/MatchThreadder is down for maintenance (starting Dec 5). The bot should be back up in a few days. Keep an eye out for when it starts posting threads again - message /u/spawnofyanni if you have any questions!\n\n--------------\n\n[Look here](https://www.reddit.com/r/soccer/wiki/matchthreads) for templates, tips, and example match threads from the past if you want to know how to make your own match thread.'
				msg.reply(body=replytext)
			else:
				replytext = ""
				teams = firstTryTeams(msg.body)
				for delim in delims:
					attempt = msg.body.split(delim,2)
					if attempt[0] != msg.body:
						teams = attempt
				threadStatus,text = createMatchInfo(teams[0],teams[1])
				print(getTimestamp() + f"Grabbing Match info for {teams[0]} vs {teams[1]}")
				if threadStatus == 0: # successfully found info
					replytext = "Below is the information for the match you've requested.\n\nIf you're using [RES](http://redditenhancementsuite.com/), you can use the 'source' button below this message to copy/paste the exact formatting code. If you aren't, you'll have to add the formatting yourself.\n\n----------\n\n" + text
				if threadStatus == 1: # not found
					replytext = "Sorry, I couldn't find info for that match. In the future I'll account for more matches around the world."
				msg.reply(body=replytext)
				print(getTimestamp() + replytext if threadStatus != 0 else "Match Info Sent")
		
		if msg.subject.lower() == 'delete':
			if msg.author.name == admin:
				name = deleteThread(msg.body)
				if messaging:
					replytext = ""
					if name != '':
						replytext = "Deleted " + name
					else:
						replytext = "Thread not found"
					msg.reply(body=replytext)
			else:
				name = removeWrongThread(msg.body,msg.author.name)
				if messaging:
					if name == 'thread':
						replytext = "Thread not found - please double-check thread ID"
					elif name == 'time':
						replytext = "This thread is more than five minutes old - thread deletion from now is an admin feature only. You can message /u/" + admin + " if you'd still like the thread to be deleted."
					elif name == 'req':
						replytext = "Username not recognised. Only the thread requester and bot admin have access to this feature."
					else:
						replytext = "Deleted " + name
					msg.reply(body=replytext)
	if len(activeThreads) > 0:						
		print(getTimestamp() + "All messages checked.")
	#r.inbox.mark_read(unread_messages)
				
def getExtraInfo(matchID):
    try:
        url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            match_data = response.json()

            notes = match_data.get("header", {}).get("competitions", [{}])[0].get("notes", [])

            if notes:
                return notes[0]  
            else:
                return ''  
        else:
            print(f"Failed to fetch match details. Status code: {response.status_code}")
            return ''
    except requests.exceptions.RequestException as e:
        print(f"Error during the request: {e}")
        return ''
				
# update score, scorers
def updateScore(matchID, t1, t2, sub):
    try:
        url = f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/summary?region=gb&lang=en&contentorigin=espn&event={matchID}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        match_data = response.json()  

        boxscore = match_data.get("header", {}).get("competitions", [])[0]
        home_score = boxscore["competitors"][0]["score"]
        away_score = boxscore["competitors"][1]["score"] 
        score = f"{home_score}-{away_score}"

        t1_scorers = []
        t2_scorers = []

        events = match_data.get("commentary", [])
        for event in events:
            event_type = event.get("play", {}).get("type", {}).get("text", "")
            if event_type in ["Goal", "Penalty Scored", "Own Goal"]:
                goal_time = event.get("time", {}).get("displayValue", "")
                participants = event.get("play", {}).get("participants", [])
                if participants:
                    goal_player = participants[0].get("athlete", {}).get("displayName", "")
                else:
                    goal_player = "Unknown"

                goal_team = event.get("play", {}).get("team", {}).get("displayName", "")

                if event_type == "Goal":
                    if goal_team == t1:
                        t1_scorers.append(f"{goal_player} ({goal_time})")
                    elif goal_team == t2:
                        t2_scorers.append(f"{goal_player} ({goal_time})")
                elif event_type == "Penalty Scored":
                    if goal_team == t1:
                        t1_scorers.append(f"{goal_player} ({goal_time} PEN)")
                    elif goal_team == t2:
                        t2_scorers.append(f"{goal_player} ({goal_time} PEN)")
                elif event_type == "Own Goal":
                    if goal_team == t1: 
                        t2_scorers.append(f"{goal_player} ({goal_time} OG)")  
                    elif goal_team == t2: 
                        t1_scorers.append(f"{goal_player} ({goal_time} OG)")

        status = getStatus(matchID)
        match_text = f"{status} #**{t1} {score} {t2}**\n\n"
        
        if t1_scorers:
            match_text += f"{t1} scorers: " + ", ".join(t1_scorers) + "\n"
        
        if t2_scorers:
            match_text += f"{t2} scorers: " + ", ".join(t2_scorers) + "\n"
        
        return match_text
    
    except requests.exceptions.Timeout:
        return "#**--**\n\n"
    except Exception as e:
        return print(e)
		
def createPMT(sub, title, body):
	print(getTimestamp() + "Submitting PMT for " + title + "...", end='')
	try:
		thread = r.subreddit(sub).submit('Post ' + title,selftext=body,send_replies=False)
		print("complete.")
		return True,thread
	except:
		print("failed.")
		logger.exception("[SUBMIT ERROR:]")
		return False,''
		
# update all current threads			
def updateThreads():
	toRemove = []

	for data in activeThreads:
		finished = False				
		index = activeThreads.index(data)
		matchID,team1,team2,thread_id,reqr,sub,type = data
		thread = r.submission(thread_id)
		body = thread.selftext
		#print getTimestamp() + team1 + ' ' + team2
		venueIndex = body.index('**Venue:**')

		markup = loadMarkup(subreddit)
		
		# detect if finished
		if getStatus(matchID) == 'FT' or getStatus(matchID) == 'AET' or getStatus(matchID) == 'Abandoned':
			finished = True
		elif getStatus(matchID) == 'FT-Pens':
			info = getExtraInfo(matchID)
			finished = True
			if 'wins' in info or 'win' in info:
				info = info.replace('wins','win')
			
		# update lineups
		team1Start,team1Sub,team2Start,team2Sub = getLineUps(matchID)
		lineupIndex = body.index('**LINE-UPS**')
		bodyTilThen = body[venueIndex:lineupIndex]
		
		t1id,t2id = getTeamIDs(matchID)
		newbody = writeLineUps(sub,bodyTilThen,team1,t1id,team2,t2id,team1Start,team1Sub,team2Start,team2Sub)
		newbody += '\n\n------------\n\n' + markup[evnts] + ' **MATCH EVENTS** | *via [ESPN](http://www.espn.com/soccer/match?gameId=' + matchID + ')*\n\n'
		
		botstat,statmsg = getBotStatus()
		if botstat != 'green':
			newbody += '*' + statmsg + '*\n\n'
			
		# update scorelines
		score = updateScore(matchID,team1,team2,sub)
		newbody = score + '\n\n--------\n\n' + newbody
		
		events = grabEvents(matchID,sub)
		newbody += '\n\n' + events
		newbody += "\n\n--------\n\n*^(Don't see a thread for a match you're watching?) [^(Click here)](https://www.reddit.com/r/soccer/wiki/matchthreads#wiki_match_thread_bot) ^(to learn how to request a match thread from this bot.)*"

		# save data
		if newbody != body:
			logger.info("Making edit to %s vs %s (/r/%s)", team1,team2,sub)
			print(getTimestamp() + "Making edit to " + team1 + " vs " + team2 + " (/r/" + sub + ")")
			thread.edit(body=newbody)
			saveData()
		newdata = matchID,team1,team2,thread_id,reqr,sub,type
		activeThreads[index] = newdata
		
		if finished:
			toRemove.append(newdata)
			if (sub in ['matchthreaddertest','soccerdev2']) and (thread.num_comments >= 0):
				createPMT(sub,thread.title,newbody)
			
	for getRid in toRemove:
		activeThreads.remove(getRid)
		logger.info("Active threads: %i - removed %s vs %s (/r/%s)", len(activeThreads), getRid[1], getRid[2], getRid[5])
		print(getTimestamp() + "Active threads: " + str(len(activeThreads)) + " - removed " + getRid[1] + " vs " + getRid[2] + " (/r/" + getRid[5] + ")")
		saveData()

logger = logging.getLogger('a')
logger.setLevel(logging.INFO)
logfilename = 'log.log'
handler = logging.handlers.RotatingFileHandler(logfilename,maxBytes = 50000,backupCount = 5) 
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.warning("[STARTUP]")
print(getTimestamp() + "[STARTUP]")

r,admin,username,password,subreddit,user_agent,id,secret,redirect = setup()
readData()

if len(sys.argv) > 1:
	if sys.argv[1] == '--reset':
		resetAll()
	if sys.argv[1] == '--flush':
		flushMsgs()


running = True
retries = 0
while running:
	try:
		if retries >= 60:
			resetAll()
			flushMsgs()
		checkAndCreate()
		updateThreads()
		retries = 0
		sleep(60)
	except KeyboardInterrupt:
		logger.warning("[MANUAL SHUTDOWN]")
		print(getTimestamp() + "[MANUAL SHUTDOWN]\n")
		running = False
	except praw.exceptions.APIException:
		retries += 1
		print(getTimestamp() + "API error, check log file [retries = " + str(retries) + "]")
		logger.exception("[API ERROR:]")
		sleep(60)
	except UnicodeDecodeError:
		retries += 1
		print(getTimestamp() + "UnicodeDecodeError, check log file [retries = " + str(retries) + "]")
		logger.exception("[UNICODE ERROR:]")
		flushMsgs()
	except UnicodeEncodeError:
		retries += 1
		print(getTimestamp() + "UnicodeEncodeError, check log file [retries = " + str(retries) + "]")
		logger.exception("[UNICODE ERROR:]")
		flushMsgs()
	except Exception:
		retries += 1
		print(getTimestamp() + "Unknown error, check log file [retries = " + str(retries) + "]")
		logger.exception("[UNKNOWN ERROR:]")
		sleep(60) 
