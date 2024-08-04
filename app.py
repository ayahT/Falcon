import os
import pickle
import base64
import json
import re
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_openai import ChatOpenAI
import streamlit as st
from bs4 import BeautifulSoup  # Import BeautifulSoup

# Initialize the ChatOpenAI instance
AI71_BASE_URL = "https://api.ai71.ai/v1/"
AI71_API_KEY = "ai71-api-1505741d-83e9-4ee9-91ea-a331d47a4680"
llm = ChatOpenAI(model="tiiuae/falcon-180B-chat", api_key=AI71_API_KEY, base_url=AI71_BASE_URL)


def remove_unwanted_text(text):
    """Remove unwanted text from the language model's response."""
    return re.sub(r'User:\s*$', '', text).strip()

def chunk_text(text, max_length):
    """Chunk long text into smaller parts."""
    chunks = []
    while len(text) > max_length:
        chunk = text[:max_length]
        last_boundary = chunk.rfind('. ')
        if last_boundary == -1:
            last_boundary = chunk.rfind('\n')
        if last_boundary == -1:
            last_boundary = len(chunk)
        chunks.append(text[:last_boundary+1])
        text = text[last_boundary+1:]
    if text:
        chunks.append(text)
    return chunks

def summarize_text(text, model):
    """Summarize text using the language model."""
    chunks = chunk_text(text, max_length=1000)  # Adjust max_length according to model's context
    summaries = [model.invoke(input=f"Summarize this text:\n{chunk}").content for chunk in chunks]
    combined_summary = ' '.join(summaries)
    final_summary = model.invoke(input=f"Organize this combined text:\n{combined_summary}").content
    return remove_unwanted_text(final_summary)

def structure_text(text):
    try:
        cleaned_text = text
        structured_text = summarize_text(cleaned_text, llm)
        return structured_text
    except Exception as e:
        st.error(f"An error occurred while structuring: {e}")
        return None

def authenticate_google_api():
    """Authenticate and return Google API service object."""
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    return build('gmail', 'v1', credentials=creds)

def remove_html_and_css(text):
    """Remove HTML tags and CSS from the text."""
    soup = BeautifulSoup(text, 'html.parser')
    return soup.get_text()

def retrieve_emails(service, hours):
    """Retrieve emails from Gmail within the past 'hours' and return a list of email data."""
    now = datetime.utcnow()
    past_time = now - timedelta(hours=hours)
    past_time_str = past_time.strftime('%Y/%m/%d')
    query = f'newer_than:{hours}h'
    
    results = service.users().messages().list(
        userId='me',
        labelIds=['INBOX'],
        q=query,
        maxResults=10
    ).execute()
    
    messages = results.get('messages', [])
    email_data = []

    for message in messages:
        msg = service.users().messages().get(userId='me', id=message['id']).execute()
        payload = msg['payload']
        headers = payload['headers']
        
        subject = ""
        sender = ""
        for header in headers:
            if header['name'] == 'Subject':
                subject = header['value']
            if header['name'] == 'From':
                sender = header['value']
        
        body = ""
        if 'parts' in payload:
            for part in payload['parts']:
                data = part['body'].get('data')
                if data:
                    body += base64.urlsafe_b64decode(data).decode()
        else:
            data = payload['body'].get('data')
            if data:
                body += base64.urlsafe_b64decode(data).decode()
        body=remove_html_and_css(body)
        body = structure_text(body)
        
        email_data.append({
            'sender': sender,
            'subject': subject,
            'content': body
        })
    
    return email_data

def create_context(emails):
    """Create context for the language model from the email data."""
    context = "Here is the email data:\n\n"
    for email in emails:
        context += f"From: {email['sender']}\nSubject: {email['subject']}\nContent: {email['content']}\n\n"
    return context

def main():
    st.title("Time Saver")
    
    # Add a slider and button to the sidebar
    with st.sidebar:
        hours = st.slider("Retrieve emails from the past (hours)", min_value=0, max_value=24, value=1)
        retrieve_button = st.button("Retrieve Emails")

    if retrieve_button:
        service = authenticate_google_api()
        emails = retrieve_emails(service, hours=hours)
        st.session_state.emails = emails  # Store emails in session state

    # Initialize session state for chat messages if not already done
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    # Display existing chat history
    for message in st.session_state.messages:
        with st.chat_message(message['role']):
            st.write(message['content'])

    # User input for new message
    prompt = st.chat_input("What would you like to ask about the emails?")

    if prompt:
        # Display user message in chat message container
        with st.chat_message("user"):
            st.write(prompt)
        
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Create context for the model
        if 'emails' in st.session_state:
            context = create_context(st.session_state.emails)
            full_prompt = f"{context}\nQuestion: {prompt}"
        
            # Query the model
            response = llm.invoke(full_prompt)
        
            # Display the model's response
            st.subheader("Model Response")
            st.write(remove_unwanted_text(response.content))

            # Append the model's response to the session state
            st.session_state.messages.append({"role": "assistant", "content": response.content})

            # Clear the input field and rerun the app
            st.rerun()  # Use experimental_rerun for better control over rerunning the app

if __name__ == '__main__':
    main()