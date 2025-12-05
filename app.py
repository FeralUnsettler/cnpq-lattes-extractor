import re
import xml.etree.ElementTree as ET
from io import BytesIO

import pandas as pd
import streamlit as st

# ---------------------------------------------------------
# CONFIGURAÇÃO BÁSICA DA PÁGINA
# ---------------------------------------------------------
st.set_page_config(
    page_title="Dashboard Lattes Extrator",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Dashboard Lattes Extrator")
st.markdown(
    """
Aplicação para **analisar XMLs de Currículos Lattes** gerados pelo Lattes Extrator (CNPq).

**Como usar:**
1. Gere os XMLs via Lattes Extrator.
2. Faça o upload de um ou mais arquivos XML abaixo.
3. Visualize o resumo dos currículos e detalhe da formação acadêmica.
"""
)

# ---------------------------------------------------------
# FUNÇÕES AUXILIARES
# ---------------------------------------------------------


def limpar_xml_bruto(content_bytes: bytes) -> str:
    """
    Limpa e normaliza o conteúdo XML:
    - tenta decodificar em UTF-8, se falhar usa Latin-1 (ignorando erros);
    - remove caracteres de controle proibidos em XML 1.0;
    - escapa & que não fizerem parte de entidades (&amp;, &lt;, etc).
    """
    # 1) Decodificação com fallback
    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = content_bytes.decode("latin-1", errors="ignore")

    # 2) Remover caracteres de controle inválidos no XML 1.0
    #    Faixas: 0x00–0x08, 0x0B, 0x0C, 0x0E–0x1F
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)

    # 3) Escapar & que não sejam entidades
    #    Ex: "P&D & Inovação" -> "P&amp;D &amp; Inovação"
    text = re.sub(r"&(?!#?\w+;)", "&amp;", text)

    return text


def parse_curriculo(file_obj):
    """
    Faz o parse robusto de um XML Lattes (CURRICULO-VITAE):
    - Limpa conteúdo bruto;
    - Trata namespaces;
    - Extrai dados gerais básicos para resumo.
    """
    content_bytes = file_obj.read()

    # Limpar e normalizar XML
    xml_str = limpar_xml_bruto(content_bytes)

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        st.error(f"Erro ao parsear XML {file_obj.name}: {e}")
        return None, None

    # Tag raiz pode vir com namespace: {ns}CURRICULO-VITAE
    tag_root = root.tag.split("}")[-1]
    if tag_root != "CURRICULO-VITAE":
        st.warning(
            f"Arquivo {file_obj.name} não parece ter raiz 'CURRICULO-VITAE' (tag encontrada: {tag_root})."
        )

    # ID Lattes
    id_lattes = root.attrib.get("NUMERO-IDENTIFICADOR", "")

    # Localizar DADOS-GERAIS, com ou sem namespace
    dados_gerais = None
    for child in root:
        if child.tag.endswith("DADOS-GERAIS"):
            dados_gerais = child
            break

    if dados_gerais is None:
        st.warning(f"Não encontrei DADOS-GERAIS em {file_obj.name}.")
        nome_completo = ""
        nome_citacoes = ""
        nacionalidade = ""
        pais_nasc = ""
        cidade_nasc = ""
        sexo = ""
    else:
        nome_completo = dados_gerais.attrib.get("NOME-COMPLETO", "")
        nome_citacoes = dados_gerais.attrib.get("NOME-EM-CITACOES-BIBLIOGRAFICAS", "")
        nacionalidade = dados_gerais.attrib.get("NACIONALIDADE", "")
        pais_nasc = dados_gerais.attrib.get("PAIS-DE-NASCIMENTO", "")
        cidade_nasc = dados_gerais.attrib.get("CIDADE-NASCIMENTO", "")
        sexo = dados_gerais.attrib.get("SEXO", "")

    resumo = {
        "ID Lattes": id_lattes,
        "Nome completo": nome_completo,
        "Nome em citações": nome_citacoes,
        "Nacionalidade": nacionalidade,
        "País de nascimento": pais_nasc,
        "Cidade de nascimento": cidade_nasc,
        "Sexo": sexo,
        "Arquivo": file_obj.name,
    }

    return root, resumo


def extrair_formacao(cv_root):
    """
    Extrai a formação acadêmica a partir do elemento raiz do currículo.
    Retorna lista de dicionários com registros de formação.
    """
    if cv_root is None:
        return []

    # Encontrar FORMACAO-ACADEMICA-TITULACAO (com ou sem namespace)
    formacao = None
    for child in cv_root:
        if child.tag.endswith("FORMACAO-ACADEMICA-TITULACAO"):
            formacao = child
            break

    if formacao is None:
        return []

    niveis = [
        "GRADUACAO",
        "ESPECIALIZACAO",
        "MESTRADO",
        "MESTRADO-PROFISSIONALIZANTE",
        "DOUTORADO",
        "POS-DOUTORADO",
        "LIVRE-DOCENCIA",
        "RESIDENCIA-MEDICA",
        "APERFEICOAMENTO",
        "CURSO-TECNICO-PROFISSIONALIZANTE",
        "ENSINO-FUNDAMENTAL-PRIMEIRO-GRAU",
        "ENSINO-MEDIO-SEGUNDO-GRAU",
    ]

    registros_formacao = []

    for nivel in niveis:
        # formacao.findall pode falhar com namespace, então percorremos filhos e filtramos por sufixo
        for elem in formacao:
            if not elem.tag.endswith(nivel):
                continue

            registro = {
                "Nível": nivel,
                "Nome do curso": elem.attrib.get("NOME-CURSO", ""),
                "Instituição": elem.attrib.get("NOME-INSTITUICAO", ""),
                "Status do curso": elem.attrib.get("STATUS-DO-CURSO", ""),
                "Ano início": elem.attrib.get("ANO-DE-INICIO", ""),
                "Ano conclusão": elem.attrib.get("ANO-DE-CONCLUSAO", ""),
                "Possui bolsa": elem.attrib.get("FLAG-BOLSA", ""),
                "Agência de fomento": elem.attrib.get("NOME-AGENCIA", ""),
            }
            registros_formacao.append(registro)

    return registros_formacao


# ---------------------------------------------------------
# INTERFACE PRINCIPAL
# ---------------------------------------------------------

uploaded_files = st.file_uploader(
    "Envie um ou mais arquivos XML de Currículos Lattes",
    type=["xml"],
    accept_multiple_files=True,
)

parsed_cvs = {}  # key: ID Lattes (ou nome do arquivo), value: root Element
rows_resumo = []

if uploaded_files:
    st.success(f"{len(uploaded_files)} arquivo(s) carregado(s). Processando...")

    for uf in uploaded_files:
        # Garantir que o ponteiro está no início
        uf.seek(0)
        root, resumo = parse_curriculo(uf)
        if root is not None and resumo is not None:
            # Se não tiver ID Lattes, usamos nome do arquivo como chave
            key_id = resumo["ID Lattes"] or uf.name
            parsed_cvs[key_id] = root
            rows_resumo.append(resumo)

    if rows_resumo:
        df_resumo = pd.DataFrame(rows_resumo)

        st.subheader("📊 Resumo dos Currículos")
        st.dataframe(df_resumo, use_container_width=True)

        # Download do resumo em CSV
        csv_buffer = BytesIO()
        df_resumo.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
        csv_buffer.seek(0)
        st.download_button(
            label="⬇️ Baixar resumo em CSV",
            data=csv_buffer,
            file_name="resumo_lattes.csv",
            mime="text/csv",
        )

        st.markdown("---")
        st.subheader("🔍 Detalhar formação acadêmica de um currículo")

        # Criar labels amigáveis para seleção
        labels = []
        ids = []
        for _, row in df_resumo.iterrows():
            rid = row["ID Lattes"] or row["Arquivo"]
            label = f"{row['Nome completo'] or '[Sem nome]'} ({rid})"
            labels.append(label)
            ids.append(rid)

        id_by_label = dict(zip(labels, ids))

        selected_label = st.selectbox(
            "Selecione um currículo para detalhar:",
            options=labels,
        )

        if selected_label:
            selected_id = id_by_label[selected_label]
            cv_root = parsed_cvs.get(selected_id)

            registros_formacao = extrair_formacao(cv_root)

            if registros_formacao:
                df_formacao = pd.DataFrame(registros_formacao)
                st.markdown("#### 🎓 Formação acadêmica")
                st.dataframe(df_formacao, use_container_width=True)
            else:
                st.info("Nenhuma informação de formação acadêmica encontrada para este currículo.")

        st.markdown("---")
        st.caption(
            "Baseado na estrutura do Currículo Lattes (XML) conforme schema oficial do Lattes Extrator (CNPq)."
        )
else:
    st.info("Envie pelo menos um arquivo XML de Currículo Lattes para começar.")
