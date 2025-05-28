import pandas as pd
from datetime import *
from operator import *
import plotly.express as px
import streamlit as st
import sqlite3


class Information:
    def __init__(self) -> None:
        # a nice imporovement would be a better way of storing this info more dynamically, like in an editable json file
        self.dataframe = pd.DataFrame(pd.read_csv("csvs/info.csv", dtype=str).fillna(""))
        
    def get_race_by_table_name(self, name:str)->pd.DataFrame:
        self.conn = sqlite3.connect('races.db')
        d = pd.read_sql(f"SELECT * FROM {name}", self.conn)
        self.conn.close()
        return d

        



class Race:
    def __init__(self, start_date: datetime, end_date: datetime, race_name: str) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.race_name = race_name
        self.conn = sqlite3.connect('races.db')
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
    

