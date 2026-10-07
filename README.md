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

## Variaveis de ambiente

DB_HOST=
DB_PORT=
DB_NAME=
DB_USER=
DB_PASSWORD=

POWER_AUTOMATE_APLICACAO_URL=
POWER_AUTOMATE_APLICACAO_48H_URL=
POWER_AUTOMATE_SHAPE_URL=