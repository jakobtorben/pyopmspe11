# SPDX-FileCopyrightText: 2023 NORCE
# SPDX-License-Identifier: MIT

""""
Script to write the benchmark data
"""

import os
import argparse
import csv
from io import StringIO
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d

try:
    from opm.io.ecl import EclFile as OpmFile
    from opm.io.ecl import EGrid as OpmGrid
    from opm.io.ecl import ERst as OpmRestart
    from opm.io.ecl import ESmry as OpmSummary
except ImportError:
    print("The Python package opm was not found, using resdata")
try:
    from resdata.grid import Grid
    from resdata.resfile import ResdataFile
    from resdata.summary import Summary
except ImportError:
    print("The resdata Python package was not found, using opm")

GAS_DEN_REF = 1.86843
WAT_DEN_REF = 998.108
SECONDS_IN_YEAR = 31536000
KMOL_TO_KG = 1e3 * 0.044


def main():
    """Postprocessing"""
    parser = argparse.ArgumentParser(description="Main script to plot the results")
    parser.add_argument(
        "-p",
        "--path",
        default="output",
        help="The name of the output folder ('output' by default).",
    )
    parser.add_argument(
        "-d",
        "--deck",
        default="spe11b",
        help="The simulated case ('spe11b' by default).",
    )
    parser.add_argument(
        "-r",
        "--resolution",
        default="10,1,5",
        help="Number of x, y, and z elements to write the data ('10,1,5' by default).",
    )
    parser.add_argument(
        "-t",
        "--time",
        default="25",
        help="Time interval for the spatial maps (spe11a [h]; spe11b/c [y]) ('24' by default).",
    )
    parser.add_argument(
        "-w",
        "--write",
        default="0.1",
        help="Time interval for the sparse and performance data (spe11a [h]; spe11b/c [y])"
        " ('0.1' by default).",
    )
    parser.add_argument(
        "-l",
        "--load",
        default="summary",
        help="Use the summary or restart for the interpolation in the sparse data"
        " ('summary' by default).",
    )
    parser.add_argument(
        "-g",
        "--generate",
        default="sparse",
        help="Write only the 'dense', 'performance', 'sparse', 'dense_performance', "
        "'dense_sparse', 'performance_sparse', or 'all'",
    )
    parser.add_argument(
        "-u",
        "--use",
        default="resdata",
        help="Using the 'resdata' or python package (resdata by default).",
    )
    cmdargs = vars(parser.parse_known_args()[0])
    dic = {"path": cmdargs["path"].strip()}
    dic["case"] = cmdargs["deck"].strip()
    dic["mode"] = cmdargs["generate"].strip()
    dic["load"] = cmdargs["load"].strip()
    dic["exe"] = os.getcwd()
    dic["where"] = f"{dic['exe']}/{dic['path']}/data"
    dic["use"] = cmdargs["use"].strip()
    dic["nxyz"] = np.genfromtxt(
        StringIO(cmdargs["resolution"]), delimiter=",", dtype=int
    )
    if dic["case"] == "spe11a":
        dic["spatial_t"] = float(cmdargs["time"].strip()) * 3600
        dic["sparse_t"] = 1.0 * round(float(cmdargs["write"].strip()) * 3600)
        dic["dims"] = [2.8, 1.0, 1.2]
        dic["dof"], dic["nxyz"][1] = 2, 1
    else:
        dic["spatial_t"] = float(cmdargs["time"].strip()) * SECONDS_IN_YEAR
        dic["sparse_t"] = float(cmdargs["write"].strip()) * SECONDS_IN_YEAR
        dic["dims"] = [8400.0, 1.0, 1200.0]
        dic["dof"], dic["nxyz"][1] = 3, 1
    if dic["case"] == "spe11c":
        dic["dims"][1] = 5000.0
    dic["nocellsr"] = dic["nxyz"][0] * dic["nxyz"][1] * dic["nxyz"][2]
    dic = read_times(dic)
    if dic["use"] == "opm":
        dic = read_opm(dic)
    else:
        dic = read_resdata(dic)
    if dic["mode"] in ["performance", "all", "dense_performance", "performance_sparse"]:
        performance(dic)
    if dic["mode"] in ["all", "sparse", "dense_sparse", "performance_sparse"]:
        sparse_data(dic)
    if dic["mode"] in ["all", "dense", "dense_performance", "dense_sparse"]:
        dense_data(dic)


def read_times(dic):
    """Get the time for injection and restart number"""
    with open(f"{dic['path']}/deck/dt.txt", "r", encoding="utf8") as file:
        for i, value in enumerate(csv.reader(file)):
            if i == 0:
                dic["d_t"] = float(value[0])
            elif i == 1:
                dic["initial_t"] = float(value[0])
            else:
                dic["t1_rst"] = int(value[0])
    if dic["t1_rst"] > 0:
        dic["t0_rst"] = 1
    else:
        dic["t0_rst"] = 0
    return dic


def read_resdata(dic):
    """Using resdata"""
    case = "./" + dic["path"] + "/flow/" + f"{dic['path'].upper()}"
    for name in ["unrst", "init"]:
        dic[f"{name}"] = ResdataFile(case + f".{name.upper()}")
    if dic["unrst"].has_kw("WAT_DEN"):
        dic["watDen"], dic["r_s"], dic["r_v"] = "wat_den", "rsw", "rvw"
    else:
        dic["watDen"], dic["r_s"], dic["r_v"] = "oil_den", "rs", "rv"
    dic["egrid"], dic["smspec"] = Grid(case + ".EGRID"), Summary(case + ".SMSPEC")
    names = ["sgas", dic["r_s"], "pressure", "gas_den", dic["watDen"], "gaskr"]
    if dic["case"] != "spe11a":
        names += [dic["r_v"], "temp"]
    for name in names:
        dic[f"{name}"] = list(dic["unrst"].iget_kw(name.upper()))
    for name in ["porv", "satnum", "fipnum", "dx", "dy", "dz"]:
        dic[f"{name}"] = list(dic["init"].iget_kw(name.upper())[0])
    dic["actnum"] = list(dic["egrid"].export_actnum())
    dic["actind"] = list(i for i, act in enumerate(dic["actnum"]) if act == 1)
    dic["porva"] = [porv for (porv, act) in zip(dic["porv"], dic["actnum"]) if act == 1]
    dic["nocellst"], dic["nocellsa"] = len(dic["actnum"]), sum(dic["actnum"])
    dic["norst"] = dic["unrst"].num_report_steps()
    dic["times_ts"] = list(86400.0 * dic["smspec"]["TIME"].values - dic["initial_t"])
    dic["times"] = [dic["d_t"] * j for j in range(1, dic["norst"] - dic["t1_rst"])]
    dic["notimes"] = len(dic["times"])
    dic["map_rsteps"] = [
        sum((1 if (rstep < i) else 0 for rstep in dic["smspec"].get_report_step()))
        for i in range(dic["t1_rst"] + 1, dic["norst"] + 1)
    ]
    dic["gxyz"] = [dic["egrid"].nx, dic["egrid"].ny, dic["egrid"].nz]
    dic["simxcent"] = [0.0] * len(dic["porv"])
    dic["simycent"] = [0.0] * len(dic["porv"])
    dic["simzcent"] = [0.0] * len(dic["porv"])
    for cell in dic["egrid"].cells():
        (
            dic["simxcent"][cell.global_index],
            dic["simycent"][cell.global_index],
            dic["simzcent"][cell.global_index],
        ) = (
            cell.coordinate[0],
            cell.coordinate[1],
            dic["dims"][2] - cell.coordinate[2],
        )
    return dic


def read_opm(dic):
    """Using opm"""
    dic = opm_files(dic)
    dic["actind"] = list(i for i, porv in enumerate(dic["porv"]) if porv > 0)
    dic["porva"] = list(porv for porv in dic["porv"] if porv > 0)
    dic["nocellst"], dic["nocellsa"] = len(dic["porv"]), dic["egrid"].active_cells
    dic["norst"] = len(dic["unrst"].report_steps)
    dic["times"] = [dic["d_t"] * j for j in range(1, dic["norst"] - dic["t1_rst"])]
    dic["times_ts"] = list(86400.0 * dic["smspec"]["TIME"] - dic["initial_t"])
    dic["notimes"] = len(dic["times"])
    dic["smsp_seconds"] = 86400 * dic["smspec"]["TIME"]
    if dic["case"] == "spe11a":
        temp = [0.0]
        temp += dic["times"][:-1]
    else:
        tini = dic["smsp_seconds"][-1] - dic["times"][-1]
        temp = [tini + time - dic["d_t"] for time in dic["times"]]
        temp.insert(0, tini - dic["d_t"])
    dic["smsp_rst"] = [
        pd.Series(abs(dic["smsp_seconds"] - time)).argmin() + 1 for time in temp
    ]
    dic["map_rsteps"] = dic["smsp_rst"][1:]
    dic["map_rsteps"].append(len(dic["smsp_seconds"]))
    dic["gxyz"] = [
        dic["egrid"].dimension[0],
        dic["egrid"].dimension[1],
        dic["egrid"].dimension[2],
    ]
    dic = load_centers(dic)
    return dic


def opm_files(dic):
    """Extract the data from the opm output files"""
    case = "./" + dic["path"] + "/flow/" + f"{dic['path'].upper()}"
    dic["unrst"], dic["init"] = OpmRestart(case + ".UNRST"), OpmFile(case + ".INIT")
    if dic["unrst"].count("WAT_DEN", 0):
        dic["watDen"], dic["r_s"], dic["r_v"] = "wat_den", "rsw", "rvw"
    else:
        dic["watDen"], dic["r_s"], dic["r_v"] = "oil_den", "rs", "rv"
    dic["egrid"], dic["smspec"] = OpmGrid(case + ".EGRID"), OpmSummary(case + ".SMSPEC")
    names = ["sgas", dic["r_s"], "pressure", "gas_den", dic["watDen"], "gaskr"]
    if dic["case"] != "spe11a":
        names += [dic["r_v"], "temp"]
    for name in names:
        dic[f"{name}"] = []
        for rst in dic["unrst"].report_steps:
            dic[f"{name}"].append(list(dic["unrst"][name.upper(), rst]))
    for name in ["porv", "satnum", "fipnum", "dx", "dy", "dz"]:
        dic[f"{name}"] = list(dic["init"][name.upper()])
    return dic


def load_centers(dic):
    """opm.io.ecl.EGrid.xyz_from_ijk is returning nan values, that's why we do this"""
    dic["simxcent"] = [0.0] * len(dic["porv"])
    dic["simycent"] = [0.0] * len(dic["porv"])
    dic["simzcent"] = [0.0] * len(dic["porv"])
    with open(f"{dic['path']}/deck/centers.txt", "r", encoding="utf8") as file:
        for j, row in enumerate(csv.reader(file)):
            dic["simxcent"][j] = float(row[0])
            dic["simycent"][j] = float(row[1])
            dic["simzcent"][j] = dic["dims"][2] - float(row[2])
    return dic


def performance(dic):
    """Write the performance within the benchmark format SECONDS_IN_YEAR"""
    dic["times_s"] = np.linspace(
        0, dic["times"][-1], round(dic["times"][-1] / dic["sparse_t"]) + 1
    )
    dic["infosteps"] = []
    with open(
        f"{dic['path']}/flow/{dic['path'].upper()}.INFOSTEP", "r", encoding="utf8"
    ) as file:
        for j, row in enumerate(csv.reader(file)):
            if j > 0:
                if float((row[0].strip()).split()[0]) >= (
                    (dic["initial_t"] - dic["sparse_t"]) / 86400.0
                ):
                    dic["infosteps"].append(
                        [float(column) for column in (row[0].strip()).split()]
                    )
    infotimes = [
        infostep[0] * 86400 - dic["initial_t"] for infostep in dic["infosteps"]
    ]
    dic["map_info"] = [
        dic["t0_rst"] + int(np.floor(infotime / dic["sparse_t"]))
        for infotime in infotimes
    ]
    fsteps = [1.0 * (infostep[11] == 0) for infostep in dic["infosteps"]]
    nress = [infostep[8] for infostep in dic["infosteps"]]
    tlinsols = [infostep[4] for infostep in dic["infosteps"]]
    runtimes = [sum(infostep[i] for i in [2, 4, 5, 6]) for infostep in dic["infosteps"]]
    liniters = [infostep[10] for infostep in dic["infosteps"]]
    nliters = [infostep[9] for infostep in dic["infosteps"]]
    dic["tsteps"] = [
        86400 * infostep[1] * infostep[11] for infostep in dic["infosteps"]
    ]
    if dic["use"] == "opm":
        fgip = dic["smspec"]["FGIP"]
        times = 86400.0 * dic["smspec"]["TIME"] - dic["initial_t"]
    else:
        fgip = dic["smspec"]["FGIP"].values
        times = 86400.0 * dic["smspec"]["TIME"].values - dic["initial_t"]
    interp_fgip = interp1d(
        times,
        GAS_DEN_REF * fgip,
        fill_value="extrapolate",
    )
    dic["text"] = []
    dic["text"].append(
        "# t [s], tstep [s], fsteps [-], mass [kg], dof [-], nliter [-], "
        + "nres [-], liniter [-], runtime [s], tlinsol [s]"
    )
    if dic["t0_rst"] == 0:
        dic["text"].append(
            "0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, "
            + "0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00"
        )
        dic["times_s"] = np.delete(dic["times_s"], 0)
    for j, time in enumerate(dic["times_s"]):
        dic["tstep"] = [
            dic["tsteps"][k]
            for k, i in enumerate(dic["map_info"])
            if i == j and dic["tsteps"][k] > 0
        ]
        if dic["tstep"]:
            dic["tstep"] = sum(dic["tstep"]) / len(dic["tstep"])
        else:
            dic["tstep"] = dic["sparse_t"]
        dic["text"].append(
            f"{time:.3e}, "
            + f"{dic['tstep']:.3e}, "
            + f"{sum(fsteps[k] for k, i in enumerate(dic['map_info']) if i==j):.3e}, "
            + f"{interp_fgip(time):.3e}, "
            + f"{dic['dof'] * dic['nocellsa']:.3e}, "
            + f"{sum(nliters[k] for k, i in enumerate(dic['map_info']) if i==j):.3e}, "
            + f"{sum(nress[k] for k, i in enumerate(dic['map_info']) if i==j):.3e}, "
            + f"{sum(liniters[k] for k, i in enumerate(dic['map_info']) if i==j):.3e}, "
            + f"{sum(runtimes[k] for k, i in enumerate(dic['map_info']) if i==j):.3e}, "
            + f"{sum(tlinsols[k] for k, i in enumerate(dic['map_info']) if i==j):.3e}"
        )
    with open(
        f"{dic['where']}/{dic['case']}_performance_time_series.csv",
        "w",
        encoding="utf8",
    ) as file:
        file.write("\n".join(dic["text"]))


def create_from_summary(dic):
    """Use the summary arrays for the sparse data interpolation"""
    if dic["use"] == "opm":
        for key in dic["smspec"].keys():
            if key[0:4] == "BGPR":
                if len(dic["pop1"]) == 0:
                    dic["pop1"] = [
                        dic["pressure"][0][dic["fipnum"].index(8)] * 1.0e5
                    ] + list(
                        dic["smspec"][key] * 1.0e5
                    )  # Pa
                else:
                    dic["pop2"] = [
                        dic["pressure"][0][dic["fipnum"].index(9)] * 1.0e5
                    ] + list(
                        dic["smspec"][key] * 1.0e5
                    )  # Pa
                    break
        dic["moba"] = (
            dic["smspec"]["RGCDM:2"]
            + dic["smspec"]["RGCDM:4"]
            + dic["smspec"]["RGCDM:5"]
            + dic["smspec"]["RGCDM:8"]
        ) * KMOL_TO_KG
        dic["imma"] = (
            dic["smspec"]["RGCDI:2"]
            + dic["smspec"]["RGCDI:4"]
            + dic["smspec"]["RGCDI:5"]
            + dic["smspec"]["RGCDI:8"]
        ) * KMOL_TO_KG
        dic["dissa"] = (
            dic["smspec"]["RWCD:2"]
            + dic["smspec"]["RWCD:4"]
            + dic["smspec"]["RWCD:5"]
            + dic["smspec"]["RWCD:8"]
        ) * KMOL_TO_KG
        dic["seala"] = (
            dic["smspec"]["RWCD:5"]
            + dic["smspec"]["RGCDM:5"]
            + dic["smspec"]["RGCDI:5"]
            + dic["smspec"]["RWCD:8"]
            + dic["smspec"]["RGCDM:8"]
            + dic["smspec"]["RGCDI:8"]
        ) * KMOL_TO_KG
        dic["mobb"] = (dic["smspec"]["RGCDM:3"] + dic["smspec"]["RGCDM:6"]) * KMOL_TO_KG
        dic["immb"] = (dic["smspec"]["RGCDI:3"] + dic["smspec"]["RGCDI:6"]) * KMOL_TO_KG
        dic["dissb"] = (dic["smspec"]["RWCD:3"] + dic["smspec"]["RWCD:6"]) * KMOL_TO_KG
        dic["sealb"] = (
            dic["smspec"]["RWCD:6"]
            + dic["smspec"]["RGCDM:6"]
            + dic["smspec"]["RGCDI:6"]
        ) * KMOL_TO_KG
        dic["sealt"] = (
            dic["seala"]
            + dic["sealb"]
            + (
                dic["smspec"]["RWCD:7"]
                + dic["smspec"]["RGCDM:7"]
                + dic["smspec"]["RGCDI:7"]
                + dic["smspec"]["RWCD:8"]
                + dic["smspec"]["RGCDM:8"]
                + dic["smspec"]["RGCDI:8"]
            )
            * KMOL_TO_KG
        )
        if dic["case"] != "spe11a":
            sealbound = (
                dic["smspec"]["RWCD:10"]
                + dic["smspec"]["RGCDM:10"]
                + dic["smspec"]["RGCDI:10"]
            ) * KMOL_TO_KG
            dic["sealt"] += sealbound
            dic["boundtot"] = (
                sealbound
                + (
                    dic["smspec"]["RWCD:11"]
                    + dic["smspec"]["RGCDM:11"]
                    + dic["smspec"]["RGCDI:11"]
                )
                * KMOL_TO_KG
            )
    else:
        for key in dic["smspec"].keys():
            if key[0:4] == "BGPR":
                if len(dic["pop1"]) == 0:
                    dic["pop1"] = [
                        dic["pressure"][0][dic["fipnum"].index(8)] * 1.0e5
                    ] + list(
                        dic["smspec"][key].values * 1.0e5
                    )  # Pa
                else:
                    dic["pop2"] = [
                        dic["pressure"][0][dic["fipnum"].index(9)] * 1.0e5
                    ] + list(
                        dic["smspec"][key].values * 1.0e5
                    )  # Pa
                    break
        dic["moba"] = (
            dic["smspec"]["RGCDM:2"].values
            + dic["smspec"]["RGCDM:4"].values
            + dic["smspec"]["RGCDM:5"].values
            + dic["smspec"]["RGCDM:8"].values
        ) * KMOL_TO_KG
        dic["imma"] = (
            dic["smspec"]["RGCDI:2"].values
            + dic["smspec"]["RGCDI:4"].values
            + dic["smspec"]["RGCDI:5"].values
            + dic["smspec"]["RGCDI:8"].values
        ) * KMOL_TO_KG
        dic["dissa"] = (
            dic["smspec"]["RWCD:2"].values
            + dic["smspec"]["RWCD:4"].values
            + dic["smspec"]["RWCD:5"].values
            + dic["smspec"]["RWCD:8"].values
        ) * KMOL_TO_KG
        dic["seala"] = (
            dic["smspec"]["RWCD:5"].values
            + dic["smspec"]["RGCDM:5"].values
            + dic["smspec"]["RGCDI:5"].values
            + dic["smspec"]["RWCD:8"].values
            + dic["smspec"]["RGCDM:8"].values
            + dic["smspec"]["RGCDI:8"].values
        ) * KMOL_TO_KG
        dic["mobb"] = (
            dic["smspec"]["RGCDM:3"].values + dic["smspec"]["RGCDM:6"].values
        ) * KMOL_TO_KG
        dic["immb"] = (
            dic["smspec"]["RGCDI:3"].values + dic["smspec"]["RGCDI:6"].values
        ) * KMOL_TO_KG
        dic["dissb"] = (
            dic["smspec"]["RWCD:3"].values + dic["smspec"]["RWCD:6"].values
        ) * KMOL_TO_KG
        dic["sealb"] = (
            dic["smspec"]["RWCD:6"].values
            + dic["smspec"]["RGCDM:6"].values
            + dic["smspec"]["RGCDI:6"].values
        ) * KMOL_TO_KG
        dic["sealt"] = (
            dic["seala"]
            + dic["sealb"]
            + (
                dic["smspec"]["RWCD:7"].values
                + dic["smspec"]["RGCDM:7"].values
                + dic["smspec"]["RGCDI:7"].values
                + dic["smspec"]["RWCD:9"].values
                + dic["smspec"]["RGCDM:9"].values
                + dic["smspec"]["RGCDI:9"].values
            )
            * KMOL_TO_KG
        )
        if dic["case"] != "spe11a":
            sealbound = (
                dic["smspec"]["RWCD:10"].values
                + dic["smspec"]["RGCDM:10"].values
                + dic["smspec"]["RGCDI:10"].values
            ) * KMOL_TO_KG
            dic["sealt"] += sealbound
            dic["boundtot"] = (
                sealbound
                + (
                    dic["smspec"]["RWCD:11"].values
                    + dic["smspec"]["RGCDM:11"].values
                    + dic["smspec"]["RGCDI:11"].values
                )
                * KMOL_TO_KG
            )
    return dic


def create_from_restart(dic):
    """Use the restart file for the sparse data interpolation"""
    dic["boxa"] = [i for i, fip in enumerate(dic["fipnum"]) if fip in (2, 4, 5, 8)]
    dic["boxb"] = [i for i, fip in enumerate(dic["fipnum"]) if fip in (3, 6)]
    dic["sensor1"] = dic["fipnum"].index(8)
    dic["sensor2"] = dic["fipnum"].index(9)
    dic["facie1"] = [sat == 1 for sat in dic["satnum"]]
    dic["facie1ind"] = [i for i, sat in enumerate(dic["satnum"]) if sat == 1]
    dic["boundariesind"] = [i for i, fip in enumerate(dic["fipnum"]) if fip in (10, 11)]
    for j in range(dic["t1_rst"], dic["norst"]):
        sgas = list(dic["sgas"][j])
        rhog = list(dic["gas_den"][j])
        k_r = list(dic["gaskr"][j])
        rhow = list(dic[f"{dic['watDen']}"][j])
        r_s = list(dic[f"{dic['r_s']}"][j])
        krp = [k_rr > 0 for k_rr in k_r]
        krm = [k_rr <= 0 for k_rr in k_r]
        co2_g = [sga * rho * por for (sga, rho, por) in zip(sgas, rhog, dic["porva"])]
        co2_d = [
            rss * rho * (1.0 - sga) * por * GAS_DEN_REF / WAT_DEN_REF
            for (rss, rho, sga, por) in zip(r_s, rhow, sgas, dic["porva"])
        ]
        dic["pop1"].append(dic["pressure"][j][dic["sensor1"]] * 1e5)  # Pa
        dic["pop2"].append(dic["pressure"][j][dic["sensor2"]] * 1e5)
        dic["moba"].append(sum(co2_g[i] * krp[i] for i in dic["boxa"]))
        dic["imma"].append(sum(co2_g[i] * krm[i] for i in dic["boxa"]))
        dic["dissa"].append(sum(co2_d[i] for i in dic["boxa"]))
        dic["seala"].append(
            sum((co2_g[i] + co2_d[i]) * dic["facie1"][i] for i in dic["boxa"])
        )
        dic["mobb"].append(sum(co2_g[i] * krp[i] for i in dic["boxb"]))
        dic["immb"].append(sum(co2_g[i] * krm[i] for i in dic["boxb"]))
        dic["dissb"].append(sum(co2_d[i] for i in dic["boxb"]))
        dic["sealb"].append(
            sum((co2_g[i] + co2_d[i]) * dic["facie1"][i] for i in dic["boxb"])
        )
        dic["sealt"].append(sum((co2_g[i] + co2_d[i]) for i in dic["facie1ind"]))
        if dic["case"] != "spe11a":
            dic["boundtot"].append(
                sum((co2_g[i] + co2_d[i]) for i in dic["boundariesind"])
            )
    return dic


def sparse_data(dic):
    """Compute the quantities in boxes A, B, and C"""
    dic["names"] = [
        "pop1",
        "pop2",
        "moba",
        "imma",
        "dissa",
        "seala",
        "mobb",
        "immb",
        "dissb",
        "sealb",
        "m_c",
        "sealt",
    ]
    if dic["case"] != "spe11a":
        dic["names"] += ["boundtot"]
    for ent in dic["names"]:
        dic[ent] = []
    dic["times_s"] = np.linspace(
        0, dic["times"][-1], round(dic["times"][-1] / dic["sparse_t"]) + 1
    )
    if dic["load"] == "summary":
        dic = create_from_summary(dic)
    else:
        dic = create_from_restart(dic)
    dic = compute_m_c(
        dic
    )  # Using the restart data until implemented in OPM Flow summary
    write_sparse_data(dic)


def compute_m_c(dic):
    """Normalized total variation of the concentration field within Box C"""
    dic["boxc"] = np.array([fip == 4 for fip in dic["fipnum"]])
    dic["boxc_x"] = list(np.roll(dic["boxc"], 1))
    dic["boxc_y"] = list(np.roll(dic["boxc"], -dic["gxyz"][0]))
    dic["boxc_z"] = list(np.roll(dic["boxc"], -dic["gxyz"][0] * dic["gxyz"][1]))
    dic["boxc"] = [i for i, fip in enumerate(dic["fipnum"]) if fip == 4]
    dic["boxc_z"] = [i for i, val in enumerate(dic["boxc_z"]) if val == 1]
    dic["boxc_y"] = [i for i, val in enumerate(dic["boxc_y"]) if val == 1]
    dic["boxc_x"] = [i for i, val in enumerate(dic["boxc_x"]) if val == 1]
    dic = max_xcw(dic)
    for j in range(dic["t1_rst"] + 1, dic["norst"]):
        sgas = list(dic["sgas"][j])
        rhow = list(dic[f"{dic['watDen']}"][j])
        r_s = list(dic[f"{dic['r_s']}"][j])
        co2_d = [
            rss * rho * (1.0 - sga) * por * GAS_DEN_REF / WAT_DEN_REF
            for (rss, rho, sga, por) in zip(r_s, rhow, sgas, dic["porva"])
        ]
        h2o_l = [
            (1 - sga) * rho * por for (sga, rho, por) in zip(sgas, rhow, dic["porva"])
        ]
        dic["xcw"] = [co2 / (co2 + h2o) for (co2, h2o) in zip(co2_d, h2o_l)]
        if dic["xcw_max"] != 0:
            dic["xcw"] = [xcw / dic["xcw_max"] for xcw in dic["xcw"]]
        if dic["case"] != "spe11c":
            dic["m_c"].append(
                sum(
                    abs((dic["xcw"][i_x] - dic["xcw"][i]) * dic["dz"][i])
                    + abs((dic["xcw"][i_z] - dic["xcw"][i]) * dic["dx"][i])
                    for (i, i_x, i_z) in zip(dic["boxc"], dic["boxc_x"], dic["boxc_z"])
                )
            )
        else:
            dic["m_c"].append(
                sum(
                    abs((dic["xcw"][i_x] - dic["xcw"][i]) * dic["dy"][i] * dic["dz"][i])
                    + abs(
                        (dic["xcw"][i_y] - dic["xcw"][i]) * dic["dx"][i] * dic["dz"][i]
                    )
                    + abs(
                        (dic["xcw"][i_z] - dic["xcw"][i]) * dic["dx"][i] * dic["dy"][i]
                    )
                    for (i, i_x, i_y, i_z) in zip(
                        dic["boxc"], dic["boxc_x"], dic["boxc_y"], dic["boxc_z"]
                    )
                )
            )
    return dic


def write_sparse_data(dic):
    """Routine to write the sparse data"""
    for name in dic["names"]:
        if dic["load"] == "summary":
            if name == "m_c":
                interp = interp1d(
                    [0.0] + dic["times"],
                    [0.0] + dic[f"{name}"],
                    fill_value="extrapolate",
                )
            elif "pop" in name:
                interp = interp1d(
                    [0.0] + dic["times_ts"],
                    dic[f"{name}"],
                    fill_value="extrapolate",
                )
            else:
                interp = interp1d(
                    [0.0] + dic["times_ts"],
                    [0.0] + list(dic[f"{name}"]),
                    fill_value="extrapolate",
                )
        else:
            if name == "m_c":
                interp = interp1d(
                    [0.0] + dic["times"],
                    [0.0] + dic[f"{name}"],
                    fill_value="extrapolate",
                )
            else:
                interp = interp1d(
                    [0.0] + dic["times"],
                    dic[f"{name}"],
                    fill_value="extrapolate",
                )
        dic[f"{name}"] = interp(dic["times_s"])
    text = [
        "# t [s], p1 [Pa], p2 [Pa], mobA [kg], immA [kg], dissA [kg], sealA [kg], "
        + "<same for B>, MC [m^2], sealTot [kg]"
    ]
    if dic["case"] != "spe11a":
        text[-1] += ", boundTot [kg]"
    for j, time in enumerate(dic["times_s"]):
        text.append(
            f"{time:.3e},{dic['pop1'][j]:.3e},{dic['pop2'][j]:.3e}"
            f",{dic['moba'][j]:.3e},{dic['imma'][j]:.3e},{dic['dissb'][j]:.3e}"
            f",{dic['seala'][j]:.3e},{dic['mobb'][j]:.3e},{dic['immb'][j]:.3e}"
            f",{dic['dissb'][j]:.3e},{dic['sealb'][j]:.3e},{dic['m_c'][j]:.3e}"
            f",{dic['sealt'][j]:.3e}"
        )
        if dic["case"] != "spe11a":
            text[-1] += f",{dic['boundtot'][j]:.3e}"
    with open(
        f"{dic['where']}/{dic['case']}_time_series.csv", "w", encoding="utf8"
    ) as file:
        file.write("\n".join(text))


def max_xcw(dic):
    """Get the maximum CO2 mass fraction in the liquid phase"""
    dic["xcw_max"] = 0
    for j in range(dic["t1_rst"], dic["norst"]):
        sgas = list(dic["sgas"][j])
        rhow = list(dic[f"{dic['watDen']}"][j])
        r_s = list(dic[f"{dic['r_s']}"][j])
        co2_d = [
            rss * rho * (1.0 - sga) * por * GAS_DEN_REF / WAT_DEN_REF
            for (rss, rho, sga, por) in zip(r_s, rhow, sgas, dic["porva"])
        ]
        h2o_l = [
            (1 - sga) * rho * por for (sga, rho, por) in zip(sgas, rhow, dic["porva"])
        ]
        xcw = [co2 / (co2 + h2o) for (co2, h2o) in zip(co2_d, h2o_l)]
        xcw_max = max(xcw[i] for i in dic["boxc"])
        dic["xcw_max"] = max(xcw_max, dic["xcw_max"])
    return dic


def dense_data(dic):
    """Write the quantities with the benchmark format"""
    d_s = round(dic["spatial_t"] / dic["d_t"])
    n_t = int(
        np.floor((dic["times"][-1 - dic["t0_rst"]] + dic["d_t"]) / dic["spatial_t"])
    )
    for i, j, k in zip(["x", "y", "z"], dic["dims"], dic["nxyz"]):
        temp = np.linspace(0, j, k + 1)
        dic[f"ref{i}cent"] = 0.5 * (temp[1:] + temp[:-1])
    ind, dic["cell_ind"] = 0, [0] * dic["nocellsr"]
    # This is very slow, it needs to be fixed
    for k in np.flip(dic["refzcent"]):
        for j in dic["refycent"]:
            for i in dic["refxcent"]:
                dic["cell_ind"][ind] = pd.Series(
                    (dic["simxcent"] - i) ** 2
                    + (dic["simycent"] - j) ** 2
                    + (dic["simzcent"] - k) ** 2
                ).argmin()
                ind += 1
    names = ["pressure", "sgas", "xco2", "xh20", "gden", "wden", "tco2"]
    if dic["case"] != "spe11a":
        names += ["temp"]
    for i in range(n_t + 1):
        print(f"Processing dense data {i+1} out of {n_t + 1}")
        t_n = i * d_s + dic["t1_rst"]
        for name in names:
            dic[f"{name}_array"] = np.array([np.nan] * dic["nocellst"])
        co2_g = [
            sga * rho * por
            for (sga, rho, por) in zip(
                dic["sgas"][t_n], dic["gas_den"][t_n], dic["porva"]
            )
        ]
        co2_d = [
            rss * rho * (1.0 - sga) * por * GAS_DEN_REF / WAT_DEN_REF
            for (rss, rho, sga, por) in zip(
                dic[f"{dic['r_s']}"][t_n],
                dic[f"{dic['watDen']}"][t_n],
                dic["sgas"][t_n],
                dic["porva"],
            )
        ]
        h2o_l = [
            (1 - sga) * rho * por
            for (sga, rho, por) in zip(
                dic["sgas"][t_n], dic[f"{dic['watDen']}"][t_n], dic["porva"]
            )
        ]
        dic["pressure_array"][dic["actind"]] = [
            1e5 * pres for pres in dic["pressure"][t_n]
        ]
        dic["sgas_array"][dic["actind"]] = dic["sgas"][t_n]
        dic["gden_array"][dic["actind"]] = [
            den if gas > 0 else 0
            for den, gas in zip(dic["gas_den"][t_n], dic["sgas"][t_n])
        ]
        dic["wden_array"][dic["actind"]] = dic[f"{dic['watDen']}"][t_n]
        dic["xco2_array"][dic["actind"]] = [
            co2 / (co2 + h2o) for (co2, h2o) in zip(co2_d, h2o_l)
        ]
        dic["xh20_array"][dic["actind"]] = 0 * dic["xco2_array"][dic["actind"]]
        dic["tco2_array"][dic["actind"]] = [
            co2d + co2g for (co2d, co2g) in zip(co2_d, co2_g)
        ]
        if dic["case"] != "spe11a":
            dic["temp_array"][dic["actind"]] = dic["temp"][t_n]
            h2o_v = [
                rvv * rho * sga * por * WAT_DEN_REF / GAS_DEN_REF
                for (rvv, rho, sga, por) in zip(
                    dic[f"{dic['r_v']}"][t_n],
                    dic["gas_den"][t_n],
                    dic["sgas"][t_n],
                    dic["porva"],
                )
            ]
            dic["xh20_array"][dic["actind"]] = [
                h2o / (h2o + co2) if (h2o + co2) > 0 else 0.0
                for (h2o, co2) in zip(h2o_v, co2_g)
            ]
        for name in names:
            dic[f"{name}_refg"] = [np.nan] * dic["nocellsr"]
            dic[f"{name}_refg"] = dic[f"{name}_array"][dic["cell_ind"]]
        write_dense_data(dic, i)


def write_dense_data(dic, i):
    """Map the quantities to the cells"""
    if dic["case"] == "spe11a":
        name_t = f"{i*round(dic['spatial_t']/3600)}h"
        text = [
            "# x [m], z [m], pressure [Pa], gas saturation [-], "
            + "mass fraction of CO2 in liquid [-], mass fraction of H20 in vapor [-], "
            + "phase mass density gas [kg/m3], phase mass density water [kg/m3], "
            + "total mass CO2 [kg]"
        ]
    elif dic["case"] == "spe11b":
        name_t = f"{i*round(dic['spatial_t']/SECONDS_IN_YEAR)}y"
        text = [
            "# x [m], z [m], pressure [Pa], gas saturation [-], "
            + "mass fraction of CO2 in liquid [-], mass fraction of H20 in vapor [-], "
            + "phase mass density gas [kg/m3], phase mass density water [kg/m3], "
            + "total mass CO2 [kg], temperature [C]"
        ]
    else:
        name_t = f"{i*round(dic['spatial_t']/SECONDS_IN_YEAR)}y"
        text = [
            "# x [m], y [m], z [m], pressure [Pa], gas saturation [-], "
            + "mass fraction of CO2 in liquid [-], mass fraction of H20 in vapor [-], "
            + "phase mass density gas [kg/m3], phase mass density water [kg/m3], "
            + "total mass CO2 [kg], temperature [C]"
        ]
    idz = 0
    for zcord in dic["refzcent"]:
        idxy = 0
        for ycord in dic["refycent"]:
            for xcord in dic["refxcent"]:
                idc = (
                    dic["nxyz"][0] * dic["nxyz"][1] * (dic["nxyz"][2] - idz - 1) + idxy
                )
                if dic["case"] == "spe11a":
                    text.append(
                        f"{xcord:.3e}, {zcord:.3e}, {dic['pressure_refg'][idc] :.3e}, "
                        + f"{dic['sgas_refg'][idc] :.3e}, {dic['xco2_refg'][idc] :.3e}, "
                        + f"{dic['xh20_refg'][idc] :.3e}, {dic['gden_refg'][idc] :.3e}, "
                        + f"{dic['wden_refg'][idc] :.3e}, {dic['tco2_refg'][idc] :.3e}"
                    )
                elif dic["case"] == "spe11b":
                    text.append(
                        f"{xcord:.3e}, {zcord:.3e}, {dic['pressure_refg'][idc] :.3e}, "
                        + f"{dic['sgas_refg'][idc] :.3e}, {dic['xco2_refg'][idc] :.3e}, "
                        + f"{dic['xh20_refg'][idc] :.3e}, {dic['gden_refg'][idc] :.3e}, "
                        + f"{dic['wden_refg'][idc] :.3e}, {dic['tco2_refg'][idc] :.3e}, "
                        + f"{dic['temp_refg'][idc] :.3e}"
                    )
                else:
                    text.append(
                        f"{xcord:.3e}, {ycord:.3e}, {zcord:.3e}, "
                        + f"{dic['pressure_refg'][idc] :.3e}, {dic['sgas_refg'][idc] :.3e}, "
                        + f"{dic['xco2_refg'][idc] :.3e}, {dic['xh20_refg'][idc] :.3e}, "
                        + f"{dic['gden_refg'][idc] :.3e}, {dic['wden_refg'][idc] :.3e}, "
                        + f"{dic['tco2_refg'][idc] :.3e}, {dic['temp_refg'][idc] :.3e}"
                    )
                idxy += 1
        idz += 1
    with open(
        f"{dic['where']}/{dic['case']}_spatial_map_{name_t}.csv", "w", encoding="utf8"
    ) as file:
        file.write("\n".join(text))


if __name__ == "__main__":
    main()
