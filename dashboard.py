import streamlit as st
import streamlit as st
from datetime import *
from class_init import *
from dashboardHelper import *
import os
import pandas as pd

check_requirements_installed()
if not authenticate_user():
    st.stop()




races = get_races()





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



