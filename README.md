# Backend Geo Mission

Backend desenvolvido em FastAPI para integração, controle e processamento de missões de aplicação agrícola.

O projeto integra dados provenientes do Power Automate com banco de dados SQL Server e informações geoespaciais dos talhões, realizando o controle das missões processadas e o armazenamento das geometrias relacionadas.

---

## Objetivo

O Backend Geo Mission tem como objetivo automatizar o processamento das aplicações agrícolas recebidas através do Power Automate.

O sistema realiza:

- Consulta de aplicações agrícolas
- Consulta das aplicações realizadas nas últimas 48 horas
- Reprocessamento automatico
- Busca de talhões através do CHAVESIG

---

## Estrutura do projeto

```text
backend-geo-mission/
│
├── src/
│   │
│   ├── main.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── database.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── aplicacao.py
│   │   └── shape.py
│   │
│   └── services/
│       ├── __init__.py
│       ├── controle_missao.py
│       ├── geometria_missao.py
│       └── rotina_aplicacao.py
│
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md