# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Este projeto é desenvolvido interativamente com Claude Code, diretamente na pasta `C:\Users\Andre\Downloads\ClaudeCodeProject`.

**Repositório GitHub:** https://github.com/andremlopes87/ClaudeCodeProject

## Regras de sincronização com o GitHub

- A cada atualização feita no projeto (novos arquivos, modificações, etc.), Claude deve automaticamente fazer commit e push para o repositório remoto no GitHub.
- Usar mensagens de commit descritivas em português.
- Branch principal: `main`.

## Convenções

- Adicionar notas de arquitetura, comandos úteis e convenções aqui conforme o projeto evoluir.

# Projeto

Este repositório existe para construir uma plataforma de agentes para uma empresa enxuta de IA.
A empresa deve operar com o mínimo possível de trabalho humano direto.
O usuário atua como decisor final, não como operador diário.

# Objetivo do produto

Construir uma plataforma capaz de:
- encontrar empresas com baixa digitalização
- analisar gargalos de vendas, atendimento, financeiro e operação
- sugerir oportunidades concretas de melhoria com agentes
- implantar agentes por função
- acompanhar resultados
- escalar a operação com o mínimo de pessoas

# Regra principal

Nunca improvise a estratégia do negócio.
Sempre siga esta ordem:
1. entender o objetivo real
2. mapear o processo atual
3. identificar gargalos
4. propor a menor solução útil
5. esperar aprovação quando houver impacto estrutural
6. implementar com testes
7. registrar o que foi decidido

# Como trabalhar neste projeto

Sempre que receber uma tarefa:
1. leia o contexto relevante
2. identifique se é tarefa de negócio, produto, arquitetura ou código
3. proponha um plano curto
4. destaque dúvidas, riscos e dependências
5. só implemente depois de ter um caminho claro
6. após implementar, rode testes e registre o que mudou

# O que você deve otimizar

Priorize sempre:
- automação real
- simplicidade
- baixo atrito
- reutilização
- clareza de logs
- facilidade de manutenção
- segurança
- possibilidade de colocar um humano para aprovar exceções

# O que evitar

Evite:
- arquitetura inchada
- telas desnecessárias
- fluxos corporativos inúteis
- abstrações prematuras
- múltiplas formas de fazer a mesma coisa
- dependência de intervenção manual para tarefas repetitivas
- código sem teste
- acoplamento forte entre agentes e canais externos

# Regras de arquitetura

Prefira:
- backend modular
- filas para tarefas assíncronas
- serviços pequenos e claros
- logs estruturados
- contratos de entrada e saída explícitos
- JSON como formato padrão entre módulos
- componentes reutilizáveis
- configuração centralizada
- features protegidas por flags quando necessário

# Modelo operacional do negócio

O negócio tem duas camadas:
1. agentes internos da própria empresa
2. agentes implantados para clientes

Nunca misture as responsabilidades dessas duas camadas.

# Primeira versão do produto

A primeira versão deve priorizar:
1. núcleo de agentes
2. fila de tarefas
3. registro de execução
4. conectores básicos
5. painel simples de acompanhamento
6. fluxo inicial de prospecção

# Primeiro fluxo a construir

Primeiro fluxo prioritário:
- encontrar empresa
- analisar sinais de atraso operacional
- gerar diagnóstico curto
- preparar mensagem de abordagem
- registrar tudo

Não tente construir tudo de uma vez.

# Aprovação humana

Escalar para o usuário quando houver:
- mudança estrutural de arquitetura
- escolha entre caminhos de produto
- risco de segurança
- dúvida sobre regra de negócio
- deploy sensível
- ação destrutiva
- uso de custo relevante

# Padrão de entrega

Toda entrega deve incluir:
- objetivo
- abordagem escolhida
- arquivos alterados
- testes executados
- riscos remanescentes
- próximos passos recomendados

# Documentação

Sempre atualize a documentação relevante quando:
- uma regra mudar
- um agente novo for criado
- um conector novo for adicionado
- um fluxo importante mudar

# Estilo

Escreva código limpo, simples e explícito.
Prefira soluções pequenas que funcionam a estruturas grandiosas sem uso real.

# Regra de custo da fase inicial

Na fase inicial do projeto, priorizar custo zero ou o mais próximo possível de zero.

Enquanto estivermos validando a estrutura operacional:
- evitar APIs pagas
- evitar ferramentas com cobrança recorrente
- priorizar fontes públicas e gratuitas
- manter a arquitetura preparada para trocar conectores no futuro

Se uma solução paga for claramente melhor, ela pode ser sugerida, mas não deve ser adotada sem aprovação explícita.

Objetivo da fase inicial:
validar a operação, o fluxo dos agentes e a utilidade do sistema antes de gastar com eficiência adicional.