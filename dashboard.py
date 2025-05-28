import streamlit as st
import streamlit as st
from datetime import *
from class_init import *
from dashboardHelper import *


# initialize info class
info = Information()
info_df = info.dataframe

races = []
for i in range(len(info_df.index)):
    start_date = datetime.strptime(info_df['Registration start date'].iloc[i], "%Y-%m-%d").date()
    end_date = datetime.strptime(info_df['Registration end date'].iloc[i], "%Y-%m-%d").date()
    races.append(Race(start_date, end_date, info_df['Name of race'].iloc[i]))




st.write("The purpose of this is to graphically see registrations, overall and by unique event year by year")
unique = sorted(races[0].dataframe['event'].unique())
unique.append("all registrations")

selector = st.radio(
    "select a type",
    unique
)



if selector == "all registrations":
    graph_it("all registrations", races)
else:
    graph_it(selector, races)



