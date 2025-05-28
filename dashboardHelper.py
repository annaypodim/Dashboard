import streamlit as st
import streamlit as st
from datetime import *
from class_init import *
import plotly.express as px



def graph_it(name:str, races) -> None:


    #to find max duration to make sure there is enough space for all graph x axis
    max_registration_durration = -1
    for i in races:
        if max_registration_durration < (i.end_date - i.start_date).days+1:
            max_registration_durration = (i.end_date - i.start_date).days+1


    # init days arr 
    days = []
    for i in range(max_registration_durration):
        days.append(max_registration_durration-i)



    data = {
        "Days Until Race": days,
    }


    names_list = []
    if name == "all registrations":
        for i in range(len(races)):
            temp_days = races[i].to_frequency()
            temp_len = len(temp_days)
            while len(temp_days) < max_registration_durration:
                temp_days.insert(0,0)

            data.update({f"{races[i].race_name:}":temp_days})

            names_list.append(races[i].race_name)
    else:
        for i in range(len(races)):
            temp_days = races[i].to_frequency_unique(name)
            temp_len = len(temp_days)
            while len(temp_days) < max_registration_durration:
                temp_days.insert(0,0)

            data.update({f"{races[i].race_name:}":temp_days})

            names_list.append(races[i].race_name)


    dataframe1 = pd.DataFrame(data)

    fig = px.line(dataframe1, x='Days Until Race', y=names_list)
    fig.update_xaxes(type='category')
    st.plotly_chart(fig)




