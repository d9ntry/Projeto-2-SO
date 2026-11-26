# Thrashing em um Servidor de Processos de Tempo Real

Projeto 2 — Sistemas Operacionais (Turma 4P)  
**Grupo:** Lucases Oliveiras  
**Integrantes:** Paulo M O Gomes, Kauã, Lucas Oliveira, Pedro Henrique da Silva Lima e Pedro Henrique Sanchez de Souza  
**Data:** 25/11/2026

## Visão geral

Este repositório reúne o relatório final e os dados experimentais do estudo sobre *thrashing* em um servidor de processos de 30 ticks/s, comparando uma **política de admissão guiada por CPU ociosa** (`naive`) com uma **política de admissão guiada por memória disponível e pressão de memória** (`corrigida`) em máquina virtual Linux.

## Conteúdo do repositório

* `Relatório Final - Thrashing em um Servidor de Processos de Tempo Real (1).pdf` — Relatório completo do grupo com metodologia, hipóteses, resultados, discussão, limites, frentes de investigação, referências e declaração de uso de IA.
* `naive_1.csv`, `naive_2.csv`, `naive_3.csv` — Coletas das 3 repetições da política ingênua (admissão baseada em uso de CPU abaixo de 70%).
* `corrigida_1.csv`, `corrigida_2.csv`, `corrigida_3.csv` — Coletas das 3 repetições da política corrigida (admissão condicionada a memória disponível acima de 200 MB, menos de 13 processos ativos e índice PSI abaixo de 5).

## Resumo dos resultados

* **Política ingênua:** A partir de 12 processos simultâneos, a memória RAM esgota, o *swap* e o `iowait` disparam (~88,4%), a mediana do tempo de tick atinge 1,18 s (pior caso de 109 s) e apenas 1 a 7 partidas concluem em 240 s.
* **Política corrigida:** Mantém cerca de 8,4 processos ativos em média, 0 MB de *swap*, tempo de tick estável em torno de 0,10 ms e 25 a 27 partidas concluídas em 240 s, acumulando fila de espera de até 86 pedidos.
