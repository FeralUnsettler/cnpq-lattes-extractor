import streamlit as st
import xml.etree.ElementTree as ET
import pandas as pd
from io import BytesIO

st.set_page_config(
    page_title="Dashboard Lattes Extrator",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Dashboard Lattes Extrator")
st.markdown(
    """
Aplicação para **analisar XMLs de Currículos Lattes** gerados pelo Lattes Extrator (CNPq).

1. Gere os XMLs via Lattes Extrator.
2. Faça o upload dos arquivos abaixo.
3. Veja um resumo dos pesquisadores e detalhe da formação acadêmica.
"""
)

uploaded_files = st.file_uploader(
    "Envie um ou mais arquivos XML de Currículos Lattes",
    type=["xml"],
    accept_multiple_files=True,
)

# Vamos manter os XMLs parseados em memória para drill-down
parsed_cvs = {}  # key: id_lattes, value: root Element
rows_resumo = []


def parse_curriculo(file_obj):
    """Parse simples de um XML Lattes (CURRICULO-VITAE)."""
    content = file_obj.read()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        st.error(f"Erro ao parsear XML {file_obj.name}: {e}")
        return None, None

    if root.tag != "CURRICULO-VITAE":
        # Em alguns casos pode vir com namespace; vamos tentar remover prefixo.
        # Ex: {algum_ns}CURRICULO-VITAE
        if not root.tag.endswith("CURRICULO-VITAE"):
            st.warning(f"Arquivo {file_obj.name} não parece ser um CURRICULO-VITAE válido.")
            return None, None

    # ID Lattes no elemento raiz
    id_lattes = root.attrib.get("NUMERO-IDENTIFICADOR", "")

    dados_gerais = root.find("DADOS-GERAIS")
    if dados_gerais is None:
        # Tentar com namespace genérico (caso venha algo como {ns}DADOS-GERAIS)
        dados_gerais = next(
            (child for child in root if child.tag.endswith("DADOS-GERAIS")),
            None,
        )

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


if uploaded_files:
    st.success(f"{len(uploaded_files)} arquivo(s) carregado(s). Processando...")

    for uf in uploaded_files:
        # Streamlit reutiliza o buffer, então precisamos resetar o ponteiro
        uf.seek(0)
        root, resumo = parse_curriculo(uf)
        if root is not None and resumo is not None:
            id_lattes = resumo["ID Lattes"] or uf.name
            parsed_cvs[id_lattes] = root
            rows_resumo.append(resumo)

    if rows_resumo:
        df_resumo = pd.DataFrame(rows_resumo)

        st.subheader("📊 Resumo dos Currículos")
        st.dataframe(df_resumo, use_container_width=True)

        # Download em CSV
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

        # Drill-down por pesquisador
        st.subheader("🔍 Detalhar formação acadêmica de um currículo")

        ids = df_resumo["ID Lattes"].tolist()
        labels = [
            f"{row['Nome completo']} ({row['ID Lattes']})"
            for _, row in df_resumo.iterrows()
        ]
        id_by_label = dict(zip(labels, ids))

        selected_label = st.selectbox(
            "Selecione um currículo para detalhar:",
            options=labels,
        )

        if selected_label:
            selected_id = id_by_label[selected_label]
            cv_root = parsed_cvs.get(selected_id)

            # Procurar bloco de formação acadêmica
            formacao = cv_root.find("FORMACAO-ACADEMICA-TITULACAO")
            if formacao is None:
                # Tentar via sufixo, em caso de namespace
                formacao = next(
                    (
                        child
                        for child in cv_root
                        if child.tag.endswith("FORMACAO-ACADEMICA-TITULACAO")
                    ),
                    None,
                )

            if formacao is None:
                st.info("Nenhuma informação de formação acadêmica encontrada.")
            else:
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
                    for elem in formacao.findall(nivel):
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

                if registros_formacao:
                    df_formacao = pd.DataFrame(registros_formacao)
                    st.markdown("#### 🎓 Formação acadêmica")
                    st.dataframe(df_formacao, use_container_width=True)
                else:
                    st.info("Bloco de formação encontrado, mas sem registros preenchidos.")

        st.markdown("---")
        st.caption(
            "Baseado no schema oficial CurriculoLattes_12_09_2022.xsd do Lattes Extrator (CNPq)."
        )
else:
    st.info("Envie pelo menos um arquivo XML de Currículo Lattes para começar.")
