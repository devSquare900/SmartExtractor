import os
import json
from groq import Groq
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# API Key load karna .env se
# Groq client initialize karna
client = Groq(
    api_key=os.environ.get("GROQ_API_KEY")
)

def extract_data_with_llm(document_text: str):
    """
    Ye function OCR se nikla hua text leta hai, usay Groq (Llama-3) ko bhejta hai,
    aur ek structured JSON (Python Dictionary) wapis karta hai.
    """
    
    # Chunking simple implementation, Groq supports 8k context for 70b, 
    # but we will just pass up to 15,000 chars to avoid token limit errors for very large PDFs
    if len(document_text) > 15000:
        document_text = document_text[:15000] + "\n...[TRUNCATED]"
    
    # 1. System Prompt (LLM ko hidayat dena ke wo kon hai aur kya karna hai)
    system_prompt = """
    You are an expert enterprise legal AI assistant.
    Your job is to read unstructured contract and invoice documents and extract specific data.
    You must output a pure JSON object with exactly these keys:
    - "execution_date": The date the contract was signed/executed. (or "N/A" if missing)
    - "expiry_date": The date the contract expires. (or "N/A" if missing)
    - "validity_tenure": The duration the contract is valid for. (or "N/A" if missing)
    - "mrc_otc": Monthly Recurring Charges or One Time Charges. (or "N/A" if missing)
    - "termination_clause": A concise summary (max 2 sentences) of the termination clause. Do not copy the full text. (or "N/A" if missing)
    
    Respond with ONLY the valid JSON object. Do not add any extra text, apologies, or markdown formatting.
    Ensure the JSON is properly closed.
    """
    
    try:
        # 2. Llama-3 ko Data Bhejna
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": f"Extract the data from this document text:\n\n{document_text}"
                }
            ],
            model="openai/gpt-oss-20b", # Fallback to available model in current context
            response_format={"type": "json_object"}, # Strict JSON lock
            temperature=0.0, # Zero creativity, 100% logic
            max_tokens=2048 # Allow enough tokens so JSON is not cut off
        )
        
        # 3. LLM ke wapis kiye hue string ko Python Dictionary mein convert karna
        result_str = chat_completion.choices[0].message.content
        
        # Clean markdown formatting if any
        result_str = result_str.strip()
        if result_str.startswith("```json"):
            result_str = result_str[7:]
        if result_str.startswith("```"):
            result_str = result_str[3:]
        if result_str.endswith("```"):
            result_str = result_str[:-3]
        result_str = result_str.strip()
            
        result_dict = json.loads(result_str)
        
        return result_dict
        
    except Exception as e:
        print(f"Error during LLM extraction: {e}")
        raise RuntimeError(f"Groq LLM Error: {str(e)}")
