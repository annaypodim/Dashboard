import pandas as pd
from datetime import *
from operator import *
import plotly.express as px
import streamlit as st
import sqlite3
from dotenv import load_dotenv
import os


def connect_db(): 
    if os.path.exists("../races.db"):
        return sqlite3.connect("../races.db")
    elif os.path.exists("races.db"):
        return sqlite3.connect("races.db")

def check_requirements_installed():
    if not os.path.exists(".env") and not os.path.exists("../.env"):
        st.write(".env file not found -- for this website to work, it must be copied over -- stoping website")
        st.stop()

    if not os.path.exists("races.db") and not os.path.exists("../races.db"):
        st.write("races.db file not found -- stopping website (required for website to function)")
        st.stop()


def load_credentials():
    if os.path.exists("../.env"):
        load_dotenv(dotenv_path="../.env")
    elif os.path.exists(".env"):
        load_dotenv()
    



# user auth code
def creds_entered():
    load_credentials()
    if st.session_state["user"].strip() == os.getenv("user") and st.session_state["passwd"].strip() == os.getenv("password"):
        st.session_state["authenticated"] = True
    else:
        st.session_state["authenticated"] = False
        st.error("Invalid username/password")

def authenticate_user():
    if "authenticated" not in st.session_state:
        st.text_input(label="username :", value="", key="user", on_change=creds_entered)
        st.text_input(label="password :", value="", key="passwd", type="password", on_change=creds_entered)
        return False
    else:
        if st.session_state["authenticated"]:
            return True
        else:
            st.text_input(label="username :", value="", key="user", on_change=creds_entered)
            st.text_input(label="password :", value="", key="passwd", type="password", on_change=creds_entered)
            return False




class Information:
    def __init__(self) -> None:
        # self.conn = sqlite3.connect("races.db", uri=True)
        self.conn = connect_db()
        self.dataframe = pd.read_sql("SELECT * FROM info", self.conn)
        self.conn.close()
        
    def get_race_by_table_name(self, race_name:str)-> pd.DataFrame:
        # self.conn = sqlite3.connect("races.db", uri=True)
        self.conn = connect_db()
        d = pd.read_sql(f"SELECT * FROM {race_name}", self.conn)
        self.conn.close()
        return d

        



class Race:
    def __init__(self, start_date: datetime, end_date: datetime, race_name: str) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.race_name = race_name
        self.conn = connect_db()
        self.dataframe = pd.read_sql(f"SELECT * FROM {self.race_name}", self.conn)
        self.conn.close()
        for i in range(len(self.dataframe)):
            string = self.dataframe['Date'].iloc[i]
            self.dataframe.at[i, 'Date'] = datetime.strptime(string, '%Y-%m-%d %H:%M:%S').date()


    # returns dataframe of events participants by a certian day and total
    def get_accumulated_unique_by_day(self, days_until_race:int) -> pd.DataFrame:
        df = self.dataframe
        day = pd.Timestamp(self.end_date-timedelta(days=days_until_race-1)).date()
        unique_events = sorted(df['event'].unique())
        nums = []
        overall_nums = []
        for event in unique_events:
            nums.append(len(df[(df.event == event) & (df.Date < day)]))
            overall_nums.append(len(df[(df.event == event)]))
        unique_events.append("all")
        nums.append(len(df[(df.Date < day)]))
        overall_nums.append(len(df))
        return pd.DataFrame({"events":unique_events,f"{days_until_race} days left": nums, "total":overall_nums})




    def to_frequency(self):
        frequency = []

        for i in range((self.end_date - self.start_date).days + 1):
            day = pd.Timestamp(self.start_date + timedelta(days=i)).date()
            frequency.append(len(self.dataframe[self.dataframe.Date == day]))
        return frequency
    


    def to_frequency_unique(self, eventt:str):
        frequency = []
        for i in range((self.end_date - self.start_date).days+1):
            day = pd.Timestamp(self.start_date + timedelta(days=i)).date()
            frequency.append(len(self.dataframe[(self.dataframe.event == eventt) & (self.dataframe.Date == day)]))
        return frequency
    
def get_races()->list:
    info = Information()
    info_df = info.dataframe
    races = []
    for i in range(len(info_df.index)):
        start_date = datetime.strptime(info_df['Registration start date'].iloc[i], "%Y-%m-%d").date()
        end_date = datetime.strptime(info_df['Registration end date'].iloc[i], "%Y-%m-%d").date()
        races.append(Race(start_date, end_date, info_df['Name'].iloc[i]))
    return races

