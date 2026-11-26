#!/usr/bin/env python3
"""
Simulador de servidor de partidas (modelo hipotético, estilo Clash Royale)
para demonstrar thrashing.

Uso (dentro da VM Linux):
    pip install psutil
    python3 simulador.py --politica naive     --out naive.csv
    python3 simulador.py --politica corrigida --out corrigida.csv

Cada "partida" é um PROCESSO que:
  - reserva size_mb de memória (estado do jogo) e a preenche (fica residente);
  - roda um loop de ticks (30/s): a cada tick acessa páginas aleatórias da
    sua memória (working set) e mede o tempo gasto no tick;
  - termina depois de `duracao_partida` segundos.
"""
import argparse, csv, multiprocessing as mp, os, random, time
import psutil

PAGE = 4096


# ---------------------------------------------------------------- partida
def partida(mid, size_mb, hz, toques, duracao, q):
    n = size_mb * 1024 * 1024
    buf = bytearray(b"\x01") * n          # força a alocação real (páginas residentes)
    paginas = n // PAGE
    periodo = 1.0 / hz
    rnd = random.randrange
    inicio = time.monotonic()
    proximo = inicio
    ult_rep = inicio
    acc = []
    while time.monotonic() - inicio < duracao:
        t0 = time.monotonic()
        for _ in range(toques):           # "lógica do jogo": mexe no estado
            buf[rnd(paginas) * PAGE] ^= 1
        acc.append((time.monotonic() - t0) * 1000)   # tempo do tick em ms
        proximo += periodo
        folga = proximo - time.monotonic()
        if folga > 0:
            time.sleep(folga)
        else:                              # estourou o tick: ressincroniza
            proximo = time.monotonic()
        agora = time.monotonic()
        if agora - ult_rep >= 1.0 and acc:
            q.put(("tick", mid, sum(acc) / len(acc), max(acc),
                   len(acc) / (agora - ult_rep)))
            acc, ult_rep = [], agora
    q.put(("fim", mid))


# ---------------------------------------------------------------- métricas
def vmstat():
    d = {}
    with open("/proc/vmstat") as f:
        for linha in f:
            k, v = linha.split()
            d[k] = int(v)
    return d


def psi_memoria():
    """Retorna avg10 do 'some' em /proc/pressure/memory (0 se indisponível)."""
    try:
        with open("/proc/pressure/memory") as f:
            for linha in f:
                if linha.startswith("some"):
                    return float(linha.split("avg10=")[1].split()[0])
    except OSError:
        pass
    return 0.0


# ---------------------------------------------------------------- servidor
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--politica", choices=["naive", "corrigida"], required=True)
    ap.add_argument("--out", default="metricas.csv")
    ap.add_argument("--size-mb", type=int, default=50, help="memória por partida")
    ap.add_argument("--hz", type=int, default=30, help="ticks por segundo")
    ap.add_argument("--toques", type=int, default=100, help="páginas tocadas por tick")
    ap.add_argument("--duracao-partida", type=int, default=60, help="segundos")
    ap.add_argument("--duracao-teste", type=int, default=240, help="segundos")
    ap.add_argument("--chegada", type=float, default=1.0, help="partidas pedidas por segundo")
    ap.add_argument("--cpu-lim", type=float, default=70.0, help="[naive] admite se CPU < lim")
    ap.add_argument("--lote", type=int, default=3, help="[naive] partidas abertas por rodada")
    ap.add_argument("--teto", type=int, default=80, help="[naive] trava de segurança")
    ap.add_argument("--max-partidas", type=int, default=0,
                    help="[corrigida] limite fixo (0 = calcula a partir da RAM)")
    ap.add_argument("--reserva-mb", type=int, default=250, help="[corrigida] RAM deixada livre")
    a = ap.parse_args()

    ram_mb = psutil.virtual_memory().total // (1024 * 1024)
    max_fixo = a.max_partidas or max(1, (ram_mb - a.reserva_mb) // (a.size_mb + 10))
    print(f"RAM={ram_mb} MB | política={a.politica} | limite corrigida={max_fixo}")

    q = mp.Queue()
    ativas = {}                 # id -> Process
    ticks_seg = []              # (media, max) recebidos no último segundo
    fila, prox_id = 0.0, 0
    ultimo = time.monotonic()
    concluidas = mortas = 0
    base = vmstat()
    psutil.cpu_percent(None); psutil.cpu_times_percent(None)

    campos = ["t", "ativas", "fila", "concluidas", "mortas", "cpu", "iowait",
              "mem_disp_mb", "swap_usado_mb", "pswpin", "pswpout", "pgmajfault",
              "psi_mem", "tick_ms_medio", "tick_ms_max", "tps_medio", "tps_total"]
    t0 = time.monotonic()
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos); w.writeheader()
        while time.monotonic() - t0 < a.duracao_teste:
            time.sleep(1.0)
            t = round(time.monotonic() - t0)

            # 1) recolhe mensagens das partidas
            ticks_seg = []
            while not q.empty():
                msg = q.get()
                if msg[0] == "tick":
                    ticks_seg.append((msg[2], msg[3], msg[4]))
                else:
                    concluidas += 1
            for mid, p in list(ativas.items()):
                if not p.is_alive():
                    if p.exitcode not in (0, None):
                        mortas += 1              # morta (ex.: OOM killer)
                    del ativas[mid]

            # 2) chegam novos pedidos de partida (proporcional ao tempo real,
            #    para o servidor travado não "receber menos jogadores")
            agora = time.monotonic()
            fila += a.chegada * (agora - ultimo)
            ultimo = agora

            # 3) política de admissão
            cpu = psutil.cpu_percent(None)
            io = getattr(psutil.cpu_times_percent(None), "iowait", 0.0)
            disp = psutil.virtual_memory().available // (1024 * 1024)
            psi = psi_memoria()

            if a.politica == "naive":
                # só olha a CPU: "está ociosa, então cabe mais"
                if cpu < a.cpu_lim and len(ativas) < a.teto:
                    n = min(int(fila), a.lote)
                else:
                    n = 0
            else:
                # olha MEMÓRIA, pressão e limite fixo; no máx. 1 por rodada
                ok = (len(ativas) < max_fixo and disp > a.size_mb + a.reserva_mb
                      and psi < 5.0)
                n = 1 if (ok and fila >= 1) else 0

            for _ in range(n):
                p = mp.Process(target=partida, args=(
                    prox_id, a.size_mb, a.hz, a.toques, a.duracao_partida, q))
                p.start(); ativas[prox_id] = p; prox_id += 1; fila -= 1

            # 4) registra métricas
            vm = vmstat()
            medio = sum(x[0] for x in ticks_seg) / len(ticks_seg) if ticks_seg else 0
            maximo = max((x[1] for x in ticks_seg), default=0)
            tps_medio = sum(x[2] for x in ticks_seg) / len(ticks_seg) if ticks_seg else 0
            tps_total = sum(x[2] for x in ticks_seg)
            w.writerow({
                "t": t, "ativas": len(ativas), "fila": int(fila),
                "concluidas": concluidas, "mortas": mortas,
                "cpu": cpu, "iowait": io, "mem_disp_mb": disp,
                "swap_usado_mb": psutil.swap_memory().used // (1024 * 1024),
                "pswpin": vm["pswpin"] - base["pswpin"],
                "pswpout": vm["pswpout"] - base["pswpout"],
                "pgmajfault": vm["pgmajfault"] - base["pgmajfault"],
                "psi_mem": psi, "tick_ms_medio": round(medio, 2),
                "tick_ms_max": round(maximo, 2),
                "tps_medio": round(tps_medio, 1), "tps_total": round(tps_total, 1)})
            f.flush()
            print(f"t={t:3d} ativas={len(ativas):3d} fila={int(fila):4d} cpu={cpu:5.1f}% "
                  f"io={io:4.1f}% disp={disp}MB tick={medio:6.1f}ms "
                  f"tps={tps_medio:4.1f} psi={psi:.1f}")

    for p in ativas.values():
        p.terminate()
    print("fim. métricas em", a.out)


if __name__ == "__main__":
    main()
