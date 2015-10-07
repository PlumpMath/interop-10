# encoding: utf-8
from __future__ import unicode_literals
import sys, os
import unittest
import urllib2

import requests
import json
import urllib
from urlparse import parse_qs
import urlparse
from requests_oauthlib import OAuth1, OAuth1Session

# TODO: Take parameters from a config file
ip = "localhost"
URL_STACKSYNC = 'http://%s:8080/v1' %(ip)
STACKSYNC_REQUEST_TOKEN_ENDPOINT = "http://%s:8080/oauth/request_token" %(ip)
STACKSYNC_ACCESS_TOKEN_ENDPOINT = "http://%s:8080/oauth/access_token" %(ip)
STACKSYNC_AUTHORIZE_ENDPOINT = "http://%s:8080/oauth/authorize" %(ip)

def put_content(oauth, file_id, file_path):
    headers = {}
    url = URL_STACKSYNC +'/file/'+str(file_id)+'/data'
    headers['StackSync-API'] = "v2"
    headers['Content-Type'] = "text/plain"
    with open (file_path, "r") as myfile:
        data=myfile.read()
    r = requests.put(url,data=data, headers=headers, auth=oauth)
    return r

def get_content(oauth, file_id):
    headers = {}
    url = URL_STACKSYNC +'/file/'+str(file_id)+'/data'
    headers['StackSync-API'] = "v2"
    headers['Content-Type'] = "application/json"
    r = requests.get(url, headers=headers, auth=oauth)
    return r

def list_root_content(oauth):
    headers = {}
    url = URL_STACKSYNC +'/folder/0'
    headers['StackSync-API'] = "v2"
    headers['Content-Type'] = "application/json"
    r = requests.get(url, headers=headers, auth=oauth)
    return r

def make(oauth, name, is_folder=False):
    headers = {}
    headers['StackSync-API'] = "v2"
    headers['Content-Type'] = "application/json"
    if not name:
        raise ValueError("Can not create a folder without name")
    if is_folder:
        url = URL_STACKSYNC +'/folder'
        parameters = {"name":str(name)}
        r = requests.post(url, json.dumps(parameters), headers=headers, auth=oauth)
        return r
    else:
        url = URL_STACKSYNC +'/file?name='+str(name)
        r = requests.post(url, headers=headers, auth=oauth)
        return r

def unlink(oauth, item_id, is_folder=False):
    headers = {}
    if is_folder:
        url = URL_STACKSYNC +'/folder/'+str(item_id)
    else:
        url = URL_STACKSYNC +'/file/'+str(item_id)

    headers['StackSync-API'] = "v2"
    headers['Content-Type'] = "text/plain"
    r = requests.delete(url, headers=headers, auth=oauth)
    return r

def move(oauth, item_id, is_folder=False):
    headers = {}
    if is_folder:
        url = URL_STACKSYNC +'/folder/'+str(item_id)
    else:
        url = URL_STACKSYNC +'/file/'+str(item_id)

    new_parent = 0
    parameters = {"parent":str(new_parent)}

    headers['StackSync-API'] = "v2"
    headers['Content-Type'] = "application/json"
    r = requests.put(url, json.dumps(parameters), headers=headers, auth=oauth)
    return r

def authenticate_request(useremail, password, client_key, client_secret):
    oauth = OAuth1(client_key=client_key, client_secret=client_secret, callback_uri='oob')
    headers = {"STACKSYNC_API":"v2"}
    try:
        r = requests.post(url=STACKSYNC_REQUEST_TOKEN_ENDPOINT, auth=oauth, headers=headers, verify=False)
        if r.status_code != 200:
            raise ValueError("Error in the authenticate process")
    except:
        raise ValueError("Error in the authenticate process")

    credentials = parse_qs(r.content)
    resource_owner_key = credentials.get('oauth_token')[0]
    resource_owner_secret = credentials.get('oauth_token_secret')[0]

    authorize_url = STACKSYNC_AUTHORIZE_ENDPOINT + '?oauth_token=' + resource_owner_key

    params = urllib.urlencode({'email': useremail, 'password': password, 'permission':'allow'})
    headers = {"Content-Type":"application/x-www-form-urlencoded", "STACKSYNC_API":"v2"}
    try:
        response = requests.post(authorize_url, data=params, headers=headers, verify=False)
    except:
        raise ValueError("Error in the authenticate process 1")
    if "application/x-www-form-urlencoded" == response.headers['Content-Type']:
        parameters = parse_qs(response.content)
        verifier = parameters.get('verifier')[0]

        oauth2 = OAuth1(client_key,
               client_secret=client_secret,
               resource_owner_key=resource_owner_key,
               resource_owner_secret=resource_owner_secret,
               verifier=verifier,
               callback_uri='oob')
        try:
            r = requests.post(url=STACKSYNC_ACCESS_TOKEN_ENDPOINT, auth=oauth2, headers=headers, verify=False)
        except:
            raise ValueError("Error in the authenticate process 2")
        credentials = parse_qs(r.content)
        resource_owner_key = credentials.get('oauth_token')[0]
        resource_owner_secret = credentials.get('oauth_token_secret')[0]

        return resource_owner_key, resource_owner_secret

    raise ValueError("Error in the authenticate process 3")
