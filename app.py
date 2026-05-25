import streamlit as st
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
import pypdf
from pypdf import PdfReader
import tempfile
import os
from typing import List

# Configuração da página
st.set_page_config(page_title="Chat com PDFs", page_icon="📚", layout="wide")

st.title("📚 Chat com PDFs usando IA Local")
st.markdown("Faça perguntas sobre seus documentos PDF de forma totalmente privada e offline!")

# Função para carregar PDF (alternativa ao PyPDFLoader)
def load_pdf(file_path: str) -> List[Document]:
    """Carrega PDF e retorna lista de documentos"""
    reader = PdfReader(file_path)
    documents = []
    
    for page_num, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        if text.strip():
            doc = Document(
                page_content=text,
                metadata={"page": page_num, "source": file_path}
            )
            documents.append(doc)
    
    return documents

# Função para dividir documentos
def split_documents(documents: List[Document], chunk_size: int = 1000) -> List[Document]:
    """Divide documentos em chunks menores"""
    chunks = []
    
    for doc in documents:
        text = doc.page_content
        metadata = doc.metadata
        
        # Divide em parágrafos primeiro
        paragraphs = text.split('\n\n')
        current_chunk = ""
        current_size = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            if current_size + para_size > chunk_size and current_chunk:
                # Salva chunk atual
                chunks.append(Document(
                    page_content=current_chunk.strip(),
                    metadata=metadata
                ))
                current_chunk = para
                current_size = para_size
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
                current_size += para_size
        
        # Último chunk
        if current_chunk:
            chunks.append(Document(
                page_content=current_chunk.strip(),
                metadata=metadata
            ))
    
    return chunks

# Sidebar para configurações
with st.sidebar:
    st.header("⚙️ Configurações")
    
    # Seleção do modelo
    model_option = st.selectbox(
        "Modelo de IA",
        ["llama3.2:1b", "llama3.2:3b", "mistral:7b", "phi3:mini"],
        help="Modelos menores são mais rápidos, maiores são mais precisos"
    )
    
    # Temperatura
    temperature = st.slider("Criatividade", 0.0, 1.0, 0.7, 0.1)
    
    # Chunk size
    chunk_size = st.slider("Tamanho dos chunks", 500, 2000, 1000, 100)
    
    st.divider()
    st.markdown("### 📌 Como usar:")
    st.markdown("1. Faça upload de um PDF")
    st.markdown("2. Espere processar")
    st.markdown("3. Faça perguntas sobre o documento")
    
    st.divider()
    st.markdown("### 🔒 Privacidade:")
    st.markdown("✅ 100% local")
    st.markdown("✅ Sem nuvem")
    st.markdown("✅ Funciona offline")

# Inicializar sessão
if "messages" not in st.session_state:
    st.session_state.messages = []
if "vectorstore" not in st.session_state:
    st.session_state.vectorstore = None
if "retriever" not in st.session_state:
    st.session_state.retriever = None

# Upload do PDF
uploaded_file = st.file_uploader("📄 Escolha um arquivo PDF", type="pdf")

if uploaded_file is not None:
    # Salvar arquivo temporário
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_path = tmp_file.name
    
    # Botão para processar
    if st.button("🔄 Processar PDF", type="primary"):
        with st.spinner("📖 Lendo PDF..."):
            # Carregar PDF
            documents = load_pdf(tmp_path)
            
            # Dividir em chunks
            chunks = split_documents(documents, chunk_size)
            
            st.success(f"✅ PDF processado! {len(chunks)} chunks criados.")
            
            # Criar embeddings
            with st.spinner("🧠 Criando embeddings..."):
                embeddings = OllamaEmbeddings(model=model_option)
                
                # Criar vectorstore
                st.session_state.vectorstore = Chroma.from_documents(
                    documents=chunks,
                    embedding=embeddings,
                    persist_directory="./chroma_db"
                )
                
                # Criar retriever
                st.session_state.retriever = st.session_state.vectorstore.as_retriever(
                    search_kwargs={"k": 3}
                )
                
                st.success("✅ Base de conhecimento criada!")
    
    # Remover arquivo temporário
    os.unlink(tmp_path)

# Chat interface
if st.session_state.vectorstore and st.session_state.retriever:
    st.divider()
    st.subheader("💬 Faça sua pergunta")
    
    # Input do usuário
    user_question = st.chat_input("Digite sua pergunta sobre o PDF...")
    
    if user_question:
        # Adicionar à história
        st.session_state.messages.append({"role": "user", "content": user_question})
        
        # Criar chain simplificada (sem depender do RetrievalQA antigo)
        with st.spinner("🤔 Pensando..."):
            # Buscar documentos relevantes
            relevant_docs = st.session_state.retriever.invoke(user_question)
            
            # Preparar contexto
            context = "\n\n".join([doc.page_content for doc in relevant_docs])
            
            # Criar prompt
            template = """Você é um assistente útil que responde perguntas baseado no contexto fornecido.
            
Contexto do documento:
{context}

Pergunta: {question}

Responda de forma clara e concisa usando APENAS as informações do contexto. 
Se a resposta não estiver no contexto, diga "Não encontrei essa informação no documento."
Resposta:"""
            
            prompt = ChatPromptTemplate.from_template(template)
            
            # Criar modelo
            llm = OllamaLLM(model=model_option, temperature=temperature)
            
            # Criar chain
            chain = (
                {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
                | prompt
                | llm
                | StrOutputParser()
            )
            
            # Executar
            answer = chain.invoke({"context": context, "question": user_question})
        
        # Adicionar resposta
        st.session_state.messages.append({"role": "assistant", "content": answer})
        
        # Mostrar fontes
        with st.expander("📖 Ver fontes utilizadas"):
            for i, doc in enumerate(relevant_docs, 1):
                st.text(f"Fonte {i} - Página {doc.metadata.get('page', '?')}:")
                st.text(doc.page_content[:300] + "...")
                st.divider()
    
    # Mostrar histórico
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

else:
    st.info("👈 Faça upload de um PDF na barra lateral para começar!")

# Footer
st.markdown("---")
st.markdown("🤖 **Chat com PDFs Local** | Usando Ollama + LangChain + ChromaDB")