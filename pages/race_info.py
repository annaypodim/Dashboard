import streamlit as st
from class_init import *


if not authenticate_user():
    st.stop()


# initialize info class
info = Information()
info_df = info.dataframe
st.write("Races found in Database")
st.dataframe(info_df)