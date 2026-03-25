import streamlit as st
from class_init import check_requirements_installed, authenticate_user, Information

check_requirements_installed()
if not authenticate_user():
    st.stop()


# initialize info class
info = Information()
info_df = info.dataframe
st.write("Races found in Database")
st.dataframe(info_df)