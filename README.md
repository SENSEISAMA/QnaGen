# QnaGen

Generate practice question papers and answer keys from PDFs with Streamlit and Qwen 3.5 9B running locally through Ollama.

## Installation

Install Git, Python 3.11+, and Ollama. Then run these commands in PowerShell:

1. Clone the repository.

   ```powershell
   git clone https://github.com/SENSEISAMA/QnaGen.git
   cd QnaGen
   ```

2. Create a virtual environment and install dependencies.

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Start Ollama and download the model.

   ```powershell
   ollama pull qwen3.5:9b
   ```

4. Run QnaGen and open the local URL shown in PowerShell.

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run app.py
   ```

## Usage

Upload PDFs with selectable text, choose a paper pattern, generate and review the questions, then download the paper and answer key. No API key is needed.
