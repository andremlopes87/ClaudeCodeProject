# Heurísticas — Módulo de Presença Digital

> Documento em construção. Será preenchido na próxima etapa da plataforma.

## Objetivo do módulo

Analisar a presença digital real de empresas já prospectadas, identificando sinais concretos de organização (ou ausência deles) nos canais online acessíveis publicamente.

## Sinais a analisar (próxima etapa)

| Sinal | Fonte | Método |
|---|---|---|
| Existência de website | Dados OSM + verificação HTTP | Requisição HEAD simples |
| Site responde (status 200) | HTTP | Requisição HEAD com timeout |
| Usa HTTPS | URL | Checar prefixo da URL |
| Telefone no site | HTML do site | Busca por padrão de telefone |
| E-mail no site | HTML do site | Busca por padrão de e-mail |
| Link para WhatsApp | HTML do site | Checar href com wa.me ou api.whatsapp.com |
| Link para Instagram | HTML do site | Checar href com instagram.com |
| Link para Facebook | HTML do site | Checar href com facebook.com |
| Chamada clara para ação (CTA) | HTML do site | Presença de botões/links de ação |

## Regras técnicas

- Sem APIs pagas
- Sem scraping frágil — apenas verificações simples e robustas
- Timeout máximo por requisição: 10s
- Não disparar nenhuma ação, apenas analisar
- Respeitar robots.txt quando aplicável

## Limitações previstas

- Apenas empresas com website identificado nos dados públicos serão analisadas
- Conteúdo dinâmico (JavaScript) não será processado nesta versão
- Análise de anúncios fora do escopo desta etapa
