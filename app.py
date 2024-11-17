import yaml
import streamlit as st
from langchain_core.output_parsers import StrOutputParser
from yaml.loader import SafeLoader
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage
from utils.chunk_doc import get_retriever
from prompt_templates.contextual_query import get_context_query_chain
from prompt_templates.qa_template import get_qa_prompt
from prompt_templates.intial_template import get_initial_chain
from operator import itemgetter
import json
import re
import os
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities import (CredentialsError,
                                               ForgotError,
                                               Hasher,
                                               LoginError,
                                               RegisterError,
                                               ResetError,
                                               UpdateError)
from db.db_connection import ChatDatabase

os.environ['LANGCHAIN_TRACING_V2'] = 'true'
os.environ['LANGCHAIN_ENDPOINT'] = 'https://api.smith.langchain.com'
os.environ['LANGCHAIN_API_KEY']= st.secrets["New_Langsmith_key"]
os.environ['LANGCHAIN_PROJECT']="default"

# Loading config file
with open('config.yaml', 'r', encoding='utf-8') as file:
    config = yaml.load(file, Loader=SafeLoader)
    
# Creating the authenticator object
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)
    
# Initialize the database manager
@st.cache_resource
def get_database():
    return ChatDatabase('enhanced_chat.db')

db = get_database()

def clear_session_messages():
    # Reset chat history when user logs out
    if "messages" in st.session_state:
        # st.session_state.messages = []
        del st.session_state.messages
        print("messages cleared")
    if "llm_chat_history" in st.session_state:
        del st.session_state["llm_chat_history"]
        print("llm_chat_history cleared")
    if "user_level" in st.session_state:
        del st.session_state["user_level"]
        print("user_level cleared")

if st.session_state["authentication_status"] is None or st.session_state["authentication_status"] is False:
    
    # Clear session state
    # for key in list(st.session_state.keys()):
    #     if key != "authentication_status":
    #         del st.session_state[key]              
    clear_session_messages()
    
    st.title('Chatbot Main Page')
    
    # Create tabs for login and registration
    tab1, tab2 = st.tabs(["Login", "Register"])

    # Login Tab
    with tab1:            
        # Creating a login widget
        try:
            authenticator.login('main')

        except LoginError as e:
            st.error(e)
        
        if st.session_state["authentication_status"] is False:
            st.error('Username/password is incorrect')
        elif st.session_state["authentication_status"] is None:
            st.warning('Please enter your username and password')

    # Registration Tab
    with tab2:
        # Creating a new user registration widget
        try:
            (email_of_registered_user,
            username_of_registered_user,
            name_of_registered_user) = authenticator.register_user()
            if email_of_registered_user:
                generated_id = db.generate_user_id()
                db.save_user_data(generated_id, "", email_of_registered_user)
                
                # Saving config file
                with open('config.yaml', 'w', encoding='utf-8') as file:
                    yaml.dump(config, file, default_flow_style=False)
                
                st.success('User registered successfully')
                st.info('Please proceed to login')

        except RegisterError as e:
            st.error(e)
else:
    if st.session_state["authentication_status"]:
            
        authenticator.logout('Logout','sidebar')
        
        # Define chatbot version for easier tracking
        chatbot_version = "1.1.0"

        # Initialize the LLM
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            # api_key=os.environ.get("OPENAI_API_KEY"),
            api_key=st.secrets["OpenAI_key"],
            temperature=0
        )
        
        # # Initialize LLM chat history (for context handling)
        if "llm_chat_history" not in st.session_state:
            st.session_state["llm_chat_history"] = []

        llm_chat_history = st.session_state["llm_chat_history"]

        st.sidebar.write("Welcome, ",st.session_state['name'])
        
        # st.sidebar.write(db.get_user_by_email(st.session_state['email']))
        
        user_info = db.get_user_by_email(st.session_state['email'])
        
        # ChatID
        chat_id = user_info['user_id']+"_1"
        
        # User Info
        user_id = user_info['user_id']
        user_email = user_info['email']
        
        # Load chat history upon successful login
        user_info = db.get_user_by_email(st.session_state['email'])
        chat_id = user_info['user_id'] + "_1"
        chat_history = db.load_chat_history(user_info['user_id'], chat_id)
        
        # Initialize chat history
        if "messages" not in st.session_state:
            st.session_state.messages = chat_history
        
        # Initialize user level
        if "user_level" not in st.session_state:
            st.session_state["user_level"] = db.get_user_level(user_id)
        user_level = st.session_state["user_level"]
        
        # if chat_history:
        #     for message in chat_history:
        #         st.session_state.messages.append(message)
        #         if message["role"] == "user":
        #             st.session_state["llm_chat_history"].append(HumanMessage(content=message["content"]))
        #         else:
        #             st.session_state["llm_chat_history"].append(AIMessage(content=message["content"]))
        
        # print("HI!!!\n",chat_history)

        retriever = get_retriever()

        contextual_query_chain = get_context_query_chain(llm)
        retriever_chain = contextual_query_chain | retriever

        qa_prompt = get_qa_prompt()
        rag_chain = (
            {
                "context": retriever_chain,
                "user_level": itemgetter("user_level"),
                "chat_history": itemgetter("chat_history"),
                "input": itemgetter("input"),
            }
            | qa_prompt
            | llm
            | StrOutputParser()
        )

        initial_chain = get_initial_chain(llm)

        st.title("DSA Chatbot")

        # Add sidebar options
        st.sidebar.title("Options")
        st.sidebar.write("Version:", chatbot_version)
        if st.sidebar.button("Clear Chat History"):
            st.session_state["llm_chat_history"] = []
            st.session_state.messages = []
            db.clear_chat_history(user_id, chat_id)

        # Add file uploader to sidebar
        uploaded_file = st.sidebar.file_uploader("Upload Files (Not Done)", type=["txt", "pdf", "docx"])

        # Process the uploaded file if available
        if uploaded_file is not None:
            file_details = {
                "filename": uploaded_file.name,
                "filetype": uploaded_file.type,
                "filesize": uploaded_file.size
            }
            st.sidebar.write("File Details:", file_details)
            # Process file content if needed; for example, reading and displaying content:
            if uploaded_file.type == "text/plain":
                file_content = uploaded_file.read().decode("utf-8")
                st.sidebar.write("File Content:", file_content)
            # Processing for other file types below

        # Display chat messages from history on app rerun
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        ####                ####
        #### For debugging  ####
        ####                ####
        def check_user_level():
            print("UL>> ",st.session_state["user_level"])

        # Accept user input
        if prompt := st.chat_input("What is an Array?"):
            # Add user message to chat history
            st.session_state.messages.append({"role": "user", "content": prompt})
            db.save_message(user_id, chat_id, "user", prompt)
            
            # Display user message in chat message container
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # Display assistant response in chat message container
            with st.chat_message("assistant"):
                
                # Initialize an empty list to hold the streamed chunks
                stream = []
                check_user_level()
                if st.session_state["user_level"] in ["","null",None]:
                    
                    print("RAN INITIAL CHAIN\n")
                    
                    response = initial_chain.invoke({
                        "input": prompt,
                        "chat_history": llm_chat_history
                    })
                    
                    print("this is the response:\n",response)
                    
                    if "{" in response and "}" in response:
                        try:
                            json_str = response[response.index("{"):response.rindex("}") + 1]
                            data = json.loads(json_str)

                            # Extract necessary fields
                            user_level = data.get("data").get("user_level")
                            db.save_user_data(user_id, user_level,user_email)

                            # Extract message from LLM
                            message = data.get("message")
                            
                            # Append and save assistant's message
                            db.save_message(user_id, chat_id, "assistant", message)

                            llm_chat_history.extend(
                                [
                                    HumanMessage(content=prompt),
                                    AIMessage(content=message),
                                ]
                            )
                            stream_message = re.findall(r'\S+|\s+', message)
                            full_response = st.write_stream(stream_message)
                            
                            # Display the full response in the chat message container
                            st.session_state.messages.append({"role": "assistant", "content": full_response})
                            
                            # Validate that necessary information is available
                            if user_level:
                                print("###############!!! User level is: ", user_level)
                                st.session_state["user_level"] = user_level

                        except json.JSONDecodeError:
                            print(response)
                            print("Oops! I broke. Sorry about that!")
                    else:
                        print("Oops! I broke. Sorry about that! JSON FAILED")
                        st.write(response)
                        st.session_state.messages.append({"role": "assistant", "content": response})
                        # Append and save assistant's message
                        db.save_message(user_id, chat_id, "assistant", response)
                        llm_chat_history.extend(
                            [
                                HumanMessage(content="Remember, you MUST generate a syntactically correct JSON object."),
                                AIMessage(content=response),
                            ]
                        )
                else:
                  # Stream the response from the RAG chain for a specific input
                    for chunk in rag_chain.stream({
                      "input": prompt,
                      "chat_history": llm_chat_history,
                        "user_level": user_level
                      }):
                      # if answer_chunk := chunk.get("answer"):
                      #     # Append the answer chunk to the stream list
                      #     stream.append(answer_chunk)
                      stream.append(chunk)

                    # Join the list of chunks to form the complete response
                    full_response = st.write_stream(stream)
                    db.save_message(user_id, chat_id, "assistant", full_response)

                    # Append the full response to the chat history
                    llm_chat_history.extend(
                        [
                            HumanMessage(content=prompt),
                            AIMessage(content=full_response),
                        ]
                    )

                    # Display the full response in the chat message container
                    st.session_state.messages.append({"role": "assistant", "content": full_response})