#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2021 Rui Ribeiro
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__ = "Rui Ribeiro"
__email__ = "rui.ribeiro@univr.it"

#system libraries
from re import sub
import sys
import os
import importlib
import urllib.request   as urllib
from glob               import glob

#Scientific Libraries
#import math
import numpy  as np
import pandas as pd
from pandas.core import construction
from scipy.optimize   import curve_fit, minimize
from sklearn.preprocessing import minmax_scale

#Plotting Libraries
import plotly.graph_objs as go
import pylab             as pl
from matplotlib import *

#PYSB
from pysb import *
from pysb.macros import *
from pysb.simulator import ScipyOdeSimulator

#Layout libraries
#import qgrid 

#directories (problem with sphinx)
abs_path=(os.path.join(os.path.split(os.getcwd())[0], 'src/lib'))
sys.path.insert(0, os.path.abspath(abs_path))
try:
    from src.lib.directories import *
    from src.lib.utils import utils
except:
    from directories import *
    from utils import *


import warnings
warnings.simplefilter(action='ignore')




#Human Target Receptors DataBase directory PATH
HuTRdb_path = os.path.join(os.getcwd(),'SSBtoolkit/src/databases/HuTRdb.sqlite3')


class convert:
    "Helper functions"
    def microgr2nanomolar(uniprotID, concentration):
        """
        This function converts micrograms of protein in nanomolar. 
        
        :parameter uniprotID: Required (str)
        :parameter concentration: Required (int): concentration od protein in micrograms
        :return: (flt) concentration of protein in nM
      
        .. note:: This function will obtain the sequence of the protein from UNIPROT and calculate automatically its molecular mass
        """

        from scipy.constants import Avogadro, micro, nano 
        #from Bio.Seq import Seq
        from Bio.SeqUtils import molecular_weight
        

        def Da2gr(x):
            return x*1.6605300000013E-24
        
        #Get protein sequence from UniProt
        seq = utils.FastaSequence(uniprotID)
        
        #Prot MW
        prot_Da = molecular_weight(seq, "protein") #Da (daltons)
        
        #convert dalton to gram and then to picograms
        prot_gr = Da2gr(prot_Da)

        #convert grams to picograms
        prot_microgr = prot_gr/micro
        prot_microgr

        #calculate protein units (experimental)
        prot_Na = concentration/prot_microgr

        #Molar concentration of prot (experimental)
        prot_M = prot_Na/Avogadro
        prot_nM = prot_M/nano
        
        return round(prot_nM,4)

    def KineticTempScale(kon, koff, T1, T2, Tu='K', *kwargs):
        """
        This function rescales the kinetics constants to a specific temperature. 
        
        :parameter kon:  Required (flt): foward kinetic constant
        :parameter koff: Required (flt): reverse kinetic constant
        :parameter T1:   Required (flt): Initial temperature
        :parameter T2:   Required (flt): Final temperature
        :paramter Tu:    Optional (kwarg str): Temperature Units (kelvin='K', celsius='C')
        :return: (flt, flt)
      
        """
        from scipy.constants import R
        from numpy import log

        #convert temperature units
        if Tu == 'K':
            pass 

        elif Tu =='C':
            T1 = T1 + 273.15     
            T2 = T2 + 273.15
        else :raise TypeError("Temperature must me in Kelvin (Tu ='K') or Celsius (Tu='C')") 


        #calculate free energies at different temperatures
        DG1 = -R*T1*log(koff/kon)

        DG2 = -R*T2*log(koff/kon)

        """if the T2 is higer than T1 (upscale)"""
        if T2 > T1:

            sf = DG2/DG1

            skon = kon*sf
            skoff = koff*sf

        """if T2 is lower than T1 (downscale)"""
        if T2 < T1:

            sf = DG2/DG1

            skon = kon*sf
            skoff = koff*sf

        if T2 == T1:
            skon = kon
            skoff = koff

        return round(skon, 3), round(skoff,3)

class get:
    '''Tools to retrive protein information'''

    def gprotein(uniprotID):
        """
        This function query the SSBtoolkit internal database to extract the G protein associated to GPCR. 
        
        .. warning:: it just works for Human GPCRS!
        
        :parameter uniprotID:  Required (str)
        :return: (str)
        """
        import sqlite3
        
        #query HuTRdb 
        dbpath = os.path.join(os.getcwd(),'src/databases/HuTRdb.sqlite3')
        conn = sqlite3.connect(dbpath)
        cur = conn.cursor()
        cur.execute("SELECT * FROM gpcr WHERE uniprotid=?", (uniprotID,))
        rows = cur.fetchall()
        conn.close()
        gprotein=rows[0][7]
        return gprotein

    class tauRAMD:
        """
        Implementation of the tRAMD method by Kokh et al., 2018.
        """

        def __init__(self):
            self._files = None
            self._dt = 2e-6
            self._softwr = 'GROMACS'
            self._prefix = None
            self.citation = '''Estimation of Drug-Target Residence Times by τ-Random Acceleration Molecular Dynamics Simulations
                                Daria B. Kokh, Marta Amaral, Joerg Bomke, Ulrich Grädler, Djordje Musil, Hans-Peter Buchstaller, Matthias K. Dreyer, Matthias Frech, Maryse Lowinski, Francois Vallee, Marc Bianciotto, Alexey Rak, and Rebecca C. Wade
                                Journal of Chemical Theory and Computation 2018 14 (7), 3859-3869
                                DOI: 10.1021/acs.jctc.8b00230 '''
            
        def Run(self, **kwargs):
            """
            Calulates the residence time of a ligand from RAMD simualtions.

            :parameter prefix: Required (kwarg str): directory path of .dat files
            :parameter dt:     Optional (kwarg flt): MD simulations time step in ns (defaul is 2E-6)
            :parameter softwr: Optional (kwarg str): software used to perform RAMD simulations: NAMD, GROMACS (default)
            :return (str): residence time
            """

            from scipy.stats import norm


            if 'prefix' not in kwargs: raise TypeError("ERROR: prefix is missing")
            if 'dt' in kwargs: self._dt = kwargs.pop('dt')
            if 'softwr' in kwargs: self._softwr = kwargs.pop('softwr')
            self._prefix = kwargs.pop('prefix')
            self._files = glob(self._prefix+'*.dat')
            self._times_set = []
            
            #Get Data
            for t,d in enumerate(self._files):
                with open(d) as f:
                    read_data = f.readlines()
                self._times = []
                for r in read_data:
                    if self._softwr == "NAMD":
                        self._times.append(int(r[r.find("EXIT:")+6:r.find(">")-2]))   # if NAMD  was used to generate RAMD trajectories
                    elif self._softwr == "GROMACS":
                        self._times.append(int(r[r.find("after")+6:r.find("steps")-1]))   # if Gromacs was used to generate RAMD trajectories
                    else: raise TypeError("ERROR: sofware unknown. options: NAMD, GROMACS")
                self._times = np.asarray(self._times)*self._dt
                self._times_set.append(self._times)
            
            #Parse Data
            self._mue_set=[]
            RTrelatives=[]
            for t, times in enumerate(self._times_set):
                if len(times) < 0: raise TypeError('ERROR: empty time values')
                else:
                    bt2 = utils.bootstrapp(times, rounds=50000)
                    mu, std = norm.fit(bt2)
                    
                    bins = len(times)
                    times = np.asarray(times)
                    hist, bin_edges = np.histogram(times,bins=bins)
                    hist_center = []
                    for i,b in enumerate(bin_edges):
                        if i > 0: hist_center.append((bin_edges[i-1]+bin_edges[i])/2.0)
                    CD = np.cumsum(hist)/np.max(np.cumsum(hist))
                    KS = np.round(np.max(np.abs(1-np.exp(-(np.asarray(hist_center))/mu) - CD)),2)
                    RTrelatives.append([t+1,mu,std,KS])
                    
                    self._mue_set.append(np.round(mu,1))
                    self._RTmean = np.round(np.mean(self._mue_set),2)
                    self._RTstd = np.round(np.std(self._mue_set),2)
                    self.RT = self._RTmean
            
            self.RTdataframe = pd.DataFrame(RTrelatives, columns=['Replica no.', 'Relative res. time', 'SD', 'KS test'])
            print("Residence time:", str(self._RTmean),'±',str(self._RTstd),'ns')
            return
        
        def plotRTdistribuitons(self,save=False, filename=None):
            """
            Plots the residence time distributions

            :parameter save:     Optional (kwarg boolean): default False
            :parameter filename: Optional (kwarg str)
            """

            import pylab as plt
            from IPython.core.display import display, HTML
            display(HTML("<style>.container { width:90% !important; }</style>"))

            fig  = plt.figure(figsize = (12,8))
            meanpointprops = dict(linestyle='--', linewidth=1.5, color='firebrick')
            medianpointprops = dict(linestyle='-', linewidth=2.0, color='orange')
            plt.boxplot(self._times_set,showmeans=True, meanline=True,meanprops=meanpointprops,medianprops = medianpointprops, bootstrap=5000)
            ymin, ymax = plt.ylim()
            plt.grid(linestyle = '--',linewidth=0.5)
            plt.yticks(np.linspace(0,int(ymax),min(int(ymax)+1,11)), fontsize=9)
            plt.ylabel('residence time [ns]', fontsize=10)
            plt.title("Residence times for "+str(len(self._files))+" replicas, mean: "+str(self._RTmean)+"  std: "+str(self._RTstd),fontsize=12)
            if save==True:
                if filename==None: 
                    filename='plot.png'
                    plt.savefig(filename, dpi=300)
                else:
                    ext = os.path.splitext(filename)[-1]
                    if ext == '.png': plt.savefig(filename, dpi=300)
                    else: raise TypeError("extension not valid. Use png")
            
            return
            
        def plotRTstats(self,save=False, filename=None):
            """
            Plots the residence time statistics

            :parameter save:     Optional (kwarg boolean): default False
            :parameter filename: Optional (kwarg str)
            """

            from matplotlib import gridspec
            from scipy.stats import norm

            import pylab as plt
            from IPython.core.display import display, HTML
            display(HTML("<style>.container { width:90% !important; }</style>"))

            fig  = plt.figure(figsize = (12,10))
            gs = gridspec.GridSpec(nrows=3, ncols=len(self._files), wspace=0.3,hspace=0.6)
            
            mue_set=[]
            for t, times in enumerate(self._times_set):

                if len(times) > 0:
                    
                #First Row
                    ax0 = fig.add_subplot(gs[0, t])

                    #histogram
                    bins = int(len(times)/2)
                    s = ax0.hist(times,bins=bins,cumulative=True,histtype="step",color='k',lw=1)

                    #plot redline at 50% of data
                    ax0.plot([min(times), max(times)],[len(times)/2,len(times)/2], color='red', alpha = 0.5, linestyle='dashed',)
                    plt.title("raw CDF",fontsize=12)
                    ax0.set_xlabel('dissociation time [ns]', fontsize=10)
                    tau = utils.ret_time(times)
                    ax0.plot([tau,tau],[0,len(times)/2.0], color='red', alpha = 0.5)
                
                #Second Row
                    bt2 = utils.bootstrapp(times, rounds=50000)
                    bins = 6
                    ax1 = fig.add_subplot(gs[1, t])
                    ax1.hist(x=bt2,bins=bins, alpha=0.8,density=True,histtype="step")
                    mu, std = norm.fit(bt2)
                    mue_set.append(np.round(mu,1))
                    xmin, xmax = plt.xlim()
                    ymin, ymax = plt.ylim()
                    x = np.linspace(0.8*xmin, xmax, 100)
                    p = norm.pdf(x, mu, std)
                    ax1.plot(x, p, 'k', linewidth=2)
                    ax1.plot([mu,mu],[0, max(p)], color='red', alpha = 0.5)
                    ax1.plot([xmin, xmax],[max(p)/2.0,max(p)/2.0], color='red', alpha = 0.5)
                    ax1.plot([0.8*xmin, mu],[max(p),max(p)], color='red', linestyle='dashed',alpha = 0.5)
                    ax1.set_xlabel('res. time [ns]', fontsize=10)
                    plt.title("tau distribution",fontsize=12)
                    ax1.set_yticks([])
                    
                #Third Row
                ax2 = fig.add_subplot(gs[2, t])
                xmin = min(times)
                xmax = np.round(max(times))
                if(xmax==0): xmax = 0.5
                tp = np.linspace(xmin*0.5,xmax*1.5,100)
                poisson = 1-np.exp(-tp/mu) #np.cumsum(1-np.exp(-np.linspace(xmin,xmax,10)/mu))
                points=len(times)
                bins = len(times)
                times = np.asarray(times)
                hist, bin_edges = np.histogram(times,bins=bins)
                hist_center = []
                for i,b in enumerate(bin_edges):
                    if i > 0: hist_center.append((bin_edges[i-1]+bin_edges[i])/2.0)
                CD = np.cumsum(hist)/np.max(np.cumsum(hist))
                ax2.scatter(np.log10(np.asarray(hist_center)),CD,marker='o')
                ax2.set_xlabel('log(res. time [ns])', fontsize=10)
                ax2.plot(np.log10(tp),poisson,color = 'k')
                ax2.set_ylim(0,1)
                ax2.set_xlim(-1.5,1.5)
                ax2.set_yticks(np.linspace(0,1,5))
                if (t> 0): ax2.set_yticklabels( [])
                plt.grid(linestyle = '--',linewidth=0.5)
                ax2.plot([np.log10(mu),np.log10(mu)],[0, 1], color='red', alpha = 0.5)
                KS = np.round(np.max(np.abs(1-np.exp(-(np.asarray(hist_center))/mu) - CD)),2)
                plt.title("KS test:"+str(KS),fontsize=12)
            
            
            if save==True:
                if filename==None: 
                    filename='plot.png'
                    plt.savefig(filename, dpi=300)
                else:
                    ext = os.path.splitext(filename)[-1]
                    if ext == '.png': plt.savefig(filename, dpi=300)
                    else: raise TypeError("extension not valid. Use png")
            
            return
    
class binding:
    """
    This class simulate ligand-target binding curves.
    """
    def __init__(self):
        self.receptor_conc = None
        self.lig_conc_range =  None
        self.pKd = None
        self.submax_concentration = None

    def bind(self, **kwargs):
        """
        Applies an function to calculate the fraction of occupited receptors at equilibrium.

        :parameter receptor_conc: Required (kwarg flt): concentration of receptor
        :parameter lig_conc_range: Required (kwarg array): array of range of ligand concentration
        :parameter pKd: Required (kwarg flt): pKd value of the ligand
        """

        if 'receptor_conc' not in kwargs: raise TypeError("ERROR: receptor_conc is missing")
        if 'lig_conc_range' not in kwargs: raise TypeError("ERROR: lig_conc_range is missing")
        if 'pKd' not in kwargs: raise TypeError("ERROR: pKd is missing")
       
        self._receptor_conc = kwargs.pop('receptor_conc')
        self._lig_conc_range = kwargs.pop('lig_conc_range')
        self._pKd = kwargs.pop('pKd')

        binding_data=[]
        for conc in self._lig_conc_range:
            binding_data.append(utils.LR_eq_conc(self._receptor_conc, conc, 0, self._pKd, 0))
        self.binding_data=binding_data
        return self.binding_data

    def maxbend(self):
        """
        Calculates the maximum bending point of a sigmoid-shaped curve according to the mathod of Sebaugh et al., 2003.
        
        :parameter drug_receptor: Required (int): concentration of the receptor
        :parameter lig_conc_range: Required (array): array of a range of ligand concentration
        :return: instance .submax_concentration (flt)
        
        .. note:: The minimization uses the Nelder-Mead method.
        """

        from scipy.optimize import curve_fit, minimize

        
        def sigmoid(X, Bottom, Top, Kd, p):
            return Bottom + (Top-Bottom)/(1+np.power((Kd/X),p))

        xfit = np.geomspace(np.min(self._lig_conc_range), np.max(self._lig_conc_range), 50000) #warning: shoud this be the minimum and maximum of concentration
        popt, pcov = curve_fit(sigmoid, self._lig_conc_range, self.binding_data, bounds=([np.min(self.binding_data),-np.inf,-np.inf, 0.5],[np.inf,np.max(self.binding_data),np.inf, 2.5]))


        def sigmoid_deriv_b(x, a,d,c,b):
            return (x/c)**b*(a - d)*np.log(x/c)/((x/c)**b + 1)**2

        min_value = minimize(sigmoid_deriv_b, np.max(xfit), args=(popt[0],popt[1],popt[2],popt[3]), method = 'Nelder-Mead')

        self.submax_concentration = round(min_value.x[0],3)
        return self.submax_concentration

    def show_curve(self):
        """
        Plots ligand-target binding curve
        """

        #import plotly
        import plotly.graph_objs as go 
        from scipy.optimize import curve_fit
        from sklearn.preprocessing import minmax_scale

        ##Fitting curve to the data

        yy = minmax_scale(self.binding_data)*100

        def equation_dose(X, Bottom, Top, EC50, p):
            return Bottom + (Top-Bottom)/(1+np.power((EC50/X),p))

        popt, pcov = curve_fit(equation_dose, self._lig_conc_range, yy, bounds=([np.min(yy),-np.inf,-np.inf, 0.5],[np.inf,np.max(yy),np.inf, 2.5]))

        xfit = np.geomspace(np.min(self._lig_conc_range), np.max(self._lig_conc_range), 50000) # These values are the same as the values for the simulation time and not ligand concentration
        yfit = minmax_scale(equation_dose(xfit, *popt))*100

        

        trace1 = go.Line(x=xfit, y=yfit, showlegend=False, name='radioligand')
        if self.submax_concentration:
            xsubmaximal = np.array(self.submax_concentration)
            ysubmaximal = np.array(equation_dose(xsubmaximal, *popt))
            trace2 = go.Scatter(x=xsubmaximal, y=ysubmaximal, showlegend=True, mode='markers', name='submaximal ({} μM)'.format(xsubmaximal),
                        marker=dict(size=14))
        else: trace2=[]


        layout = dict(title = '',
                                xaxis = dict(
                                    title = '[ligand] μM',
                                    type ='log',
                                    exponentformat='e',
                                    titlefont=dict(
                                        size=20
                                    ),
                                    tickfont=dict(
                                        size=20
                                    )),
                                yaxis = dict(
                                    title = '% occupied receptors',
            
                                    titlefont=dict(
                                        size=20),
                                    tickfont=dict(
                                    size=20)

                                ),
                                legend=dict(font=dict(size=15)),
                                autosize=False,
                                width=850,
                                height=650,
                                )
        if self.submax_concentration:
            fig = go.Figure(data=[trace1, trace2], layout=layout)
        else:
            fig = go.Figure(data=[trace1], layout=layout)
        return fig

class simulation:
    """
    This class simulates the mathematical models of the signaling pathways.
    """
    class activation:
        """
        Simulation of the activation of signaling pathways (i.e. activation by agonists)
        """
        def __init__(self):
            self._ligands=None
            self._affinities=None
            self._pathway=None 
            self._receptor_conc=None 
            self._lig_conc_range=None 
            self._ttotal=None 
            self._nsteps=None
            self._binding_kinetics=True 
            self._binding_kinetic_parameters=None
            self.simulation_data=None
            self.processed_data=None

        def SetSimulationParameters(self, **kwargs):
            """
            :parameter ligands:          Required (kwargs list): list of ligands' names (str)
            :parameter affinities:       Required (kwargs list): list of pKd values (flt)
            :parameter pathway:          Required (kwargs str): name of the pathway ('Gs', 'Gi', 'Gq') 
            :parameter receptor_conc:    Required (kwargs flt): receptors concentration (nM)
            :parameter lig_conc_range:   Required (kwargs array): range of ligands' concentration
            :parameter ttotal:           Required (kwargs int): simulation time (seconds)
            :parameter nsteps:           Required (kwargs int): simulation time step
            :parameter binding_kinetics: Optional (kwargs boolean): default (False)

            
            .. warning:: the order of the lists of ligands names and affinities list must be the same. 
            
            """
            self._ligands= kwargs.pop('ligands')
            if 'affinities' in kwargs:
                self._affinities=kwargs.pop('affinities')
            self._pathway=kwargs.pop('pathway')
            self._receptor_conc=kwargs.pop('receptor_conc') 
            self._lig_conc_range=kwargs.pop('lig_conc_range') 
            self._ttotal=kwargs.pop('ttotal') 
            self._nsteps=kwargs.pop('nsteps')
            self._binding_kinetics=kwargs.pop('binding_kinetics') 
            if 'binding_kinetic_parameters' in kwargs:self._binding_kinetic_parameters=kwargs.pop('binding_kinetic_parameters')
            self._DefaultPathwayParametersDataFrame=pd.DataFrame()

            return 

        def PathwayParameters(self):
            """
            Display table with default pathway parameters.

            .. warning:: this functions requires the qgrid library. It doens't work on Google Colab.
            """
            import qgrid
            self._DefaultPathwayParametersDataFrame =  pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))

            col_opts = { 'editable': False, 'sortable':False}
            col_defs = {'Value': { 'editable': True, 'width': 150 }}
            self._DefaultPathwayParametersTable = qgrid.show_grid(self._DefaultPathwayParametersDataFrame, column_options=col_opts,column_definitions=col_defs)
            return self._DefaultPathwayParametersTable

        def UserPathwayParameters(self, path):
            """
            Import user pathway parameters.

            :parameter path:     Required (kwarg str): directory path
            """
            import qgrid
            self._DefaultPathwayParametersDataFrame =  pd.read_csv(path)
            col_opts = { 'editable': False, 'sortable':False}
            col_defs = {'Value': { 'editable': True, 'width': 150 }}
            self._DefaultPathwayParametersTable = qgrid.show_grid(self._DefaultPathwayParametersDataFrame, column_options=col_opts,column_definitions=col_defs)
            return self._DefaultPathwayParametersTable

        def PathwayParametersToCSV(self, path):
            """
            Export pathway parameters into CSV format.

            :parameter path:     Required (kwarg str): directory path
            """
            self._DefaultPathwayParametersTable.get_changed_df().to_csv(path, index=False)
            print('saved in:', path)
            return 

        def Reactions(self):
            """
            Display pathway reactions.
            """
            from IPython.display import display, HTML
            display(HTML("<style>.container {width:90% !important}</style>"))
            return pd.read_csv('src/lib/pathways/{}_reactions.csv'.format(self._pathway))

        def Run(self):
            '''
            This function runs the pathway simulation and returns the raw simulation data.
            '''

            #Check inputs
            if self._ligands==None: raise TypeError("ligands list undefined.")
            elif self._pathway==None: raise TypeError("pathway name undefined.")
            elif self._binding_kinetics==False and self._affinities==None: raise TypeError("affinity_values_dict undefined.")
            elif self._binding_kinetics==True and self._affinities==None: pass
            elif self._lig_conc_range.any() == False: raise TypeError("lig_conc_range undefined.")
            elif self._ttotal==None: raise TypeError("ttotal undefined.")
            elif self._nsteps==None: raise TypeError("nsteps undefined.")
            elif self._receptor_conc==None: raise TypeError("receptor_conc undefined.")
            else: pass
            
            
            #Check Pathway availability and import it
            available_pathways = ['Gs', 'Gi', 'Gq']
            if self._pathway == 'Gz(Gi)': self._pathway = 'Gi'
            if self._pathway not in available_pathways: raise Exception('Unvailable Pathway. Please, introduce it manually. Pathways available: "Gs", "Gi", "Gq".')
            mypathway = importlib.import_module('.'+self._pathway, package='src.lib.pathways')
            
            #Get default pathway parameters            
            if  self._DefaultPathwayParametersDataFrame.empty and self._binding_kinetic_parameters==None:
                self._DefaultPathwayParametersDataFrame = pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))
                self._PathwayParameters = self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict()
            
            elif self._DefaultPathwayParametersDataFrame.empty is False and self._binding_kinetic_parameters is None:
                try: 
                    #extract data from qgrid
                    newparameters = self._DefaultPathwayParametersTable.get_changed_df()
                    self._PathwayParameters = newparameters.set_index('Parameter').iloc[:,0].to_dict()
                except:
                    self._PathwayParameters = self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict()

            elif self._DefaultPathwayParametersDataFrame.empty and self._binding_kinetic_parameters is not None: 
                self._DefaultPathwayParametersDataFrame = pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))
                self._PathwayParameters = {**self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict(), **self._binding_kinetic_parameters}
            
            elif self._DefaultPathwayParametersDataFrame.empty is False and self._binding_kinetic_parameters is not None:
                try: 
                    #extract data from qgrid
                    newparameters = self._DefaultPathwayParametersTable.get_changed_df()
                    self._PathwayParameters = {**newparameters.set_index('Parameter').iloc[:,0].to_dict(), **self._binding_kinetic_parameters}
                except:
                    self._PathwayParameters = {**self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict(), **self._binding_kinetic_parameters}

            #Input
            t = pl.geomspace(0.00001, self._ttotal, num=self._nsteps) # (a,b,c); a is the starting time ; b is the total time simulated ; c is the number of points
            

            #Output
            simulation_data={}

            #Function
            for ligand in self._ligands:
                ligand_name = os.path.splitext(str(ligand))[0]
                data=[]
                utils.printProgressBar(0, len(self._lig_conc_range), prefix = "{:<15}".format(ligand_name[:15]), suffix = 'Complete', length = 50)

                for idx in range(len(self._lig_conc_range)):

                    ligand_conc = self._lig_conc_range[idx]
                    if self._binding_kinetics == False:
                        #get LR conc
                        parameters = {**self._PathwayParameters, 'R_init':self._receptor_conc}
                        LR_conc_init = utils.LR_eq_conc(self._receptor_conc, ligand_conc, 0, self._affinities[self._ligands.index(ligand)], 0)
                        mymodel = mypathway.network(LR=LR_conc_init, kinetics=False, **parameters)
                        simres = ScipyOdeSimulator(mymodel, tspan=t, compiler='cython').run()
                        yout = simres.all
                    
                    elif self._binding_kinetics == True:
                        parameters={**self._PathwayParameters,'R_init':self._receptor_conc, 'L_init':self._lig_conc_range[idx] }
                        mymodel = mypathway.network(kinetics=True, **parameters)
                        simres = ScipyOdeSimulator(mymodel, tspan=t, compiler='cython').run()
                        yout = simres.all
                        
                    d1={'ligand_conc':ligand_conc, 'time':t }

                    for idx2 in range(len(mypathway.list_of_observables)):
                        d2={mypathway.list_of_observables[idx2]:yout[mypathway.list_of_observables[idx2]]}
                        d1.update(d2)
                    data.append(d1)
                    utils.printProgressBar(idx + 1, len(self._lig_conc_range), prefix = "{:<15}".format(ligand_name[:15]), suffix = 'Complete', length = 50)
                

                simulation_data[ligand_name] = {'sim_data':data,
                                            'label':ligand_name,}
            self.simulation_data = simulation_data
            return

        def Analysis(self):
            '''
            This function calculates the dose-response effect.
            
            :return: instance of processed_data
            '''
            
            if self.simulation_data == None: raise TypeError('There is no simulation data. simulation.activation.run() must be run first.')

            from sklearn.preprocessing import minmax_scale
            
            # Define all the lists and dictionaries used in this function
            raw_data=[]
            normalized_data=[]
            fitted_data=[]

            dose={}

            #defining concentration range
            lig_conc_min = self._lig_conc_range.min()
            lig_conc_max = self._lig_conc_range.max()
            
            #Main function
            for ligand in self.simulation_data:

                #definig and dictionaries used in this loop:
                raw_data_dict={}
                normalized_data_dict={}
                fitted_data_dict={}

                # Calculate dose-response curve
                #get metabolite concentration, rescale, and transform data if pathway/metabolite decrease
                # metabolite_raw is not normalized
                if self._pathway == 'Gi' or self._pathway == 'Gz(Gi)':
                    metabolite='cAMP'
                    metabolite_conc_raw=[]
                    for i in range(len(self._lig_conc_range)):
                        n=np.amax(self.simulation_data[ligand]['sim_data'][i]['obs_'+metabolite]) #cad
                        metabolite_conc_raw.append(n)
                    metabolite_conc_norm = minmax_scale(1-np.array(metabolite_conc_raw))
                elif self._pathway == 'Gs':
                    metabolite='cAMP'
                    metabolite_conc_raw=[]
                    for i in range(len(self._lig_conc_range)):
                        n=np.amax(self.simulation_data[ligand]['sim_data'][i]['obs_'+metabolite]) #cad
                        metabolite_conc_raw.append(n)
                    metabolite_conc_norm = minmax_scale(np.array(metabolite_conc_raw))
                elif self._pathway == 'Gq':
                    metabolite='IP3'
                    metabolite_conc_raw=[]
                    for i in range(len(self._lig_conc_range)):
                        n=np.amax(self.simulation_data[ligand]['sim_data'][i]['obs_'+metabolite]) #cad
                        metabolite_conc_raw.append(n)
                    metabolite_conc_norm = minmax_scale(np.array(metabolite_conc_raw))
                else: raise Exception('Unvailable Pathway. Please, introduce it manually. Networs available: "Gs", "Gi", "Gq".')


                ## save results
                raw_data_dict['x']=self._lig_conc_range
                raw_data_dict['y']=metabolite_conc_raw
                raw_data_dict['label']=self.simulation_data[ligand]['label']

                normalized_data_dict['x']=self._lig_conc_range
                normalized_data_dict['y']=metabolite_conc_norm
                normalized_data_dict['label']=self.simulation_data[ligand]['label']

                ## create a list of all data
                raw_data.append(raw_data_dict)
                normalized_data.append(normalized_data_dict)

                ##Fitting curve to the data

                def equation_dose(X, Bottom, Top, EC50, p):
                    return Bottom + (Top-Bottom)/(1+np.power((EC50/X),p))

                popt_EC50, pcov = curve_fit(equation_dose, self._lig_conc_range, metabolite_conc_norm, bounds=([np.min(metabolite_conc_norm),-np.inf,-np.inf, 0.5],[np.inf,np.max(metabolite_conc_norm),np.inf, 2.5]))

                xfit_EC50 = np.geomspace(lig_conc_min, lig_conc_max, 50000) # These values are the same as the values for the simulation time and not ligand concentration
                yfit_EC50 = equation_dose(xfit_EC50, *popt_EC50)

                fit_EC50={'x':xfit_EC50, 'y':yfit_EC50, 'label':self.simulation_data[ligand]['label']}

                dose[ligand] = {'raw_data': raw_data_dict,
                                'normalized_data':normalized_data_dict ,
                                'fitted_data': fit_EC50,
                                'EC50 (μM)': round(popt_EC50[2],5),
                                'pEC50': round(-np.log10(popt_EC50[2]*1E-6),2)}
                
            self.processed_data=dose
            return 

        def Curve(self, save=False, filename=None):
            '''
            Plots the dose-response curve.
            '''

            if self.simulation_data == None: raise TypeError('There is no simulation data. simulation.activation.run() must be run first.')

            import plotly
            import plotly.graph_objs as go
            import plotly.offline as pyoff

            colors = plotly.colors.DEFAULT_PLOTLY_COLORS

            plot_data=[]

            color_id=0
            for ligand in self.processed_data:
                trace_norm = go.Scatter(x=self.processed_data[ligand]['normalized_data']['x'],
                                        y=minmax_scale(self.processed_data[ligand]['normalized_data']['y'])*100 ,
                                        mode='markers',
                                        showlegend=True,
                                        name=self.processed_data[ligand]['normalized_data']['label'],
                                        marker=dict(color=colors[color_id]))
                plot_data.append(trace_norm)

                trace_fitted = go.Scatter(x=self.processed_data[ligand]['fitted_data']['x'],
                                    y=minmax_scale(self.processed_data[ligand]['fitted_data']['y'])*100,
                                    mode='lines',
                                    showlegend=False,
                                    name=self.processed_data[ligand]['fitted_data']['label'],
                                    line=dict(color=colors[color_id]))
                plot_data.append(trace_fitted)
                color_id +=1

            layout = dict(title = '',
                            xaxis = dict(
                                title = '[ligand] μM',
                                type ='log',
                                #range = [-3, 2],
                                exponentformat='e',
                                titlefont=dict(
                                    size=20
                                ),
                                tickfont=dict(
                                    size=20
                                )),
                            yaxis = dict(
                                title = '% Response',
                                #range = [0, 100],
                                titlefont=dict(
                                    size=20),
                                tickfont=dict(
                                size=20)

                            ),
                            legend=dict(font=dict(size=15)),
                            autosize=False,
                            width=850,
                            height=650,
                            )

            fig = go.Figure(data=plot_data, layout=layout)
            #fig['layout']['yaxis'].update(autorange = True)

            if save==True:
                if filename==None: 
                    filename='plot.html'
                    return pyoff.plot(fig, filename=filename)
                else:
                    ext = os.path.splitext(filename)[-1]
                    if ext == '.png': fig.write_image(filename, scale=3)
                    elif ext == '.html': pyoff.plot(fig, filename=filename)
                    else: raise TypeError("extension not valid. Use png or html.")
            elif save ==False: return fig
            return 
            
        def Potency(self):
            '''
            Return the potency values as a pandas DataFrame.
            '''
            import pandas as pd
            data = simulation.activation.PotencyToDict(self)
            df = pd.DataFrame.from_dict(data, orient='index')
            return df

        def PotencyToDict(self):
            '''
            Convert potencies into a dictionary.
            '''
            
            #dependencies
            if self.processed_data == None: raise TypeError('Simulation data unprocessed. simulation.activation.analysis() must be run first.')

            kvalues={}
            for ligand in self.processed_data:
                IC50 = list(self.processed_data[ligand].keys())[-2]
                IC50_value = self.processed_data[ligand][IC50]
                pIC50 = list(self.processed_data[ligand].keys())[-1]
                pIC50_value = self.processed_data[ligand][pIC50]
                kvalues[ligand]={IC50:IC50_value, pIC50:pIC50_value}
            return kvalues
           
        def PotencyToCSV(self, path):
            '''
            Exports the potency values into csv format.

            :parameter path: Required (kwarg str): directory path to save the csv file
            '''

            data = simulation.activation.PotencyToDict(self)
            df = pd.DataFrame.from_dict(data, orient='index')
            df.to_csv(path, index=False)
            return
   
    class inhibition:
        """
        Simulation of the inhibition of signaling pathways (i.e. inhibition by antagonists).
        """
        def __init__(self):
            self._agonist=None
            self._agonist_affinity=None
            self._agonist_submaximal_conc=None
            self._antagonists=None
            self._antagonists_affinities=None
            self._pathway=None 
            self._receptor_conc=None 
            self._lig_conc_range=None 
            self._ttotal=None 
            self._nsteps=None
            self._binding_kinetics=False 
            self._binding_kinetic_parameters=None
            self.simulation_data=None
            self.processed_data=None

        def SetSimulationParameters(self, **kwargs):
            """
            :parameter agonist:                 Required (kwargs str): agonist name 
            :parameter agonist_affinity:        Required (kwargs flt): agonist pKd value
            :parameter agonist_submaximal_conc: Required (kwargs flt): agonist submaximal concentration
            :parameter antagonists:             Required (kwargs list):list of antagonists names (str) 
            :parameter antagonists_affinities:  Required (kwargs list): list of antagonists affinity values (flt)
            :parameter antagonists_conc_range:  Required (kwargs array): range of ligands' concentration (nM)
            :parameter pathway:                 Required (kwargs str): name of the pathway ('Gs', 'Gi', 'Gq')
            :parameter receptor_conc:           Required (kwargs flt): receptors concentration (nM)
            :parameter ttotal:                  Required (kwargs int): simulation time (seconds)
            :parameter nsteps:                  Required (kwargs int): simulation time step
            :parameter kinetics:                Optional (kwargs boolean): default (False)


            :return: instances of all parameters
            
            .. warning:: the order of the lists of the antagonists names and affinities list must be the same. 
            
            """
            self._agonist= kwargs.pop('agonist')
            self._agonist_affinity=kwargs.pop('agonist_affinity')
            self._agonist_submaximal_conc=kwargs.pop('agonist_submaximal_conc')
            self._antagonists=kwargs.pop('antagonists')
            self._antagonists_affinities=kwargs.pop('antagonists_affinities')
            self._pathway=kwargs.pop('pathway')
            self._receptor_conc=kwargs.pop('receptor_conc') 
            self._lig_conc_range=kwargs.pop('lig_conc_range') 
            self._ttotal=kwargs.pop('ttotal') 
            self._nsteps=kwargs.pop('nsteps')
            if 'kinetics' in kwargs: 
                self._binding_kinetics=kwargs.pop('kinetics')
                if self._binding_kinetics==True: raise TypeError("The of Kinetic parameters during an inhibition simulation it is not supported yet.") 
            else: self._binding_kinetics=False
            if 'binding_kinetic_parameters' in kwargs:
                self._binding_kinetic_parameters=kwargs.pop('binding_kinetic_parameters')
            self._DefaultPathwayParametersDataFrame=pd.DataFrame()

            return 

        def PathwayParameters(self):
            """
            Display table with default pathway parameters.

            .. warning:: this functions requires the qgrid library. It doens't work on Google Colab.
            """
            import qgrid
            self._DefaultPathwayParametersDataFrame =  pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))

            col_opts = { 'editable': False, 'sortable':False}
            col_defs = {'Value': { 'editable': True, 'width': 150 }}
            self._DefaultPathwayParametersTable = qgrid.show_grid(self._DefaultPathwayParametersDataFrame, column_options=col_opts,column_definitions=col_defs)
            return self._DefaultPathwayParametersTable

        def UserPathwayParameters(self, path):
            """
            Import user pathway parameters.

            :parameter path:     Required (kwarg str): directory path
            """
            import qgrid
            self._DefaultPathwayParametersDataFrame =  pd.read_csv(path)
            col_opts = { 'editable': False, 'sortable':False}
            col_defs = {'Value': { 'editable': True, 'width': 150 }}
            self._DefaultPathwayParametersTable = qgrid.show_grid(self._DefaultPathwayParametersDataFrame, column_options=col_opts,column_definitions=col_defs)
            return self._DefaultPathwayParametersTable

        def PathwayParametersToCSV(self, path):
            """
            Export pathway parameters into CSV format.

            :parameter path:     Required (kwarg str): directory path
            """
            self._DefaultPathwayParametersTable.get_changed_df().to_csv(path, index=False)
            print('saved in:', path)
            return 
        
        def Reactions(self):
            """
            Display pathway reactions.
            """
            from IPython.display import display, HTML
            display(HTML("<style>.container {width:90% !important}</style>"))
            return pd.read_csv('src/lib/pathways/{}_reactions.csv'.format(self._pathway))

        def Run(self):
            '''
            This function runs the pathway simulation and returns the raw simulation data.
            '''

            #Check inputs
            if self._agonist==None: raise TypeError("agonist undefined.")
            elif self._agonist_affinity==None: raise TypeError("agonist_affinity undifined.")
            elif self._antagonists==None: raise TypeError("antagonists list undefined.")
            elif self._antagonists_affinities==None: raise TypeError("antagonists affinity values undefined.")
            elif self._pathway==None: raise TypeError("pathway undefined.")
            elif self._lig_conc_range.any() == False: raise TypeError("lig_conc_range undefined.")
            elif self._agonist_submaximal_conc == None: raise TypeError("agonist_submaximal_conc undifined.")
            elif self._ttotal==None: raise TypeError("ttotal undefined.")
            elif self._nsteps==None: raise TypeError("nsteps undefined.")
            elif self._receptor_conc==None: raise TypeError("receptor_conc undefined.")
            elif self._binding_kinetics==True: raise TypeError("The of Kinetic parameters during an inhibition simulation it is not supported yet.")
            else: pass

            #check pathway
            available_pathways = ['Gs', 'Gi', 'Gq']
            if self._pathway == 'Gz(Gi)': self._pathway = 'Gi'
            if self._pathway not in available_pathways: raise Exception('Unvailable Pathway. Please, introduce it manually. Networs available: "Gs", "Gi", "Gq".')
            mypathway = importlib.import_module('.'+self._pathway, package='src.lib.pathways')
            
            #Get default pathway parameters            
            if  self._DefaultPathwayParametersDataFrame.empty:
                self._DefaultPathwayParametersDataFrame = pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))
                self._PathwayParameters = self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict()
            
            elif self._DefaultPathwayParametersDataFrame.empty is False:
                try: 
                    #extract data from qgrid
                    newparameters = self._DefaultPathwayParametersTable.get_changed_df()
                    self._PathwayParameters = newparameters.set_index('Parameter').iloc[:,0].to_dict()
                except:
                    self._PathwayParameters = self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict()            

            #Input
            t = pl.geomspace(0.00001, self._ttotal, num=self._nsteps) # (a,b,c); a is the starting time ; b is the total time simulated ; c is the number of points

            #Output
            simulation_data={}

            #Function
            for ligand in self._antagonists:
                ligand_name = os.path.splitext(ligand)[0]
                data=[]
                utils.printProgressBar(0, len(self._lig_conc_range), prefix = "{:<15}".format(ligand_name[:15]), suffix = 'Complete', length = 50)

                for idx in range(len(self._lig_conc_range)):

                    ligand_conc = self._lig_conc_range[idx]

                    #get LR conc
                    parameters = {**self._PathwayParameters, 'R_init':self._receptor_conc}
                    LR_conc_init = utils.LR_eq_conc(self._receptor_conc, self._agonist_submaximal_conc, ligand_conc, self._agonist_affinity, self._antagonists_affinities[self._antagonists.index(ligand)])
                    mymodel = mypathway.network(LR=LR_conc_init, kinetics=False, **parameters)
                    simres = ScipyOdeSimulator(mymodel, tspan=t, compiler='cython').run()
                    yout = simres.all

                    d1={'ligand_conc':ligand_conc, 'time':t }

                    for idx2 in range(len(mypathway.list_of_observables)):
                        d2={mypathway.list_of_observables[idx2]:yout[mypathway.list_of_observables[idx2]]}
                        d1.update(d2)
                    data.append(d1)
                    utils.printProgressBar(idx + 1, len(self._lig_conc_range), prefix = "{:<15}".format(ligand_name[:15]), suffix = 'Complete', length = 50)

                simulation_data[ligand_name] = {'sim_data':data,
                                            'label':self._agonist+' + ' + ligand_name}

            self.simulation_data=simulation_data
            return

        def Analysis(self):
            '''
            This function calculates the dose-response effect.
            
            :return: instance processed_data
            '''
            #dependencies
            if self.simulation_data == None: raise TypeError('There is no simulation data. simulation.inhibition.run() must be run first.')


            from sklearn.preprocessing import minmax_scale

            # Define all the lists and dictionaries used in this function
            raw_data=[]
            normalized_data=[]
            fitted_data=[]

            dose={}

            #defining concentration range
            #defining concentration range
            lig_conc_min = self._lig_conc_range.min()
            lig_conc_max = self._lig_conc_range.max()

            #Main function
            for ligand in self.simulation_data:

                #definig and dictionaries used in this loop:
                raw_data_dict={}
                normalized_data_dict={}
                fitted_data_dict={}

                # Calculate dose-response curve
                #get metabolite concentration, rescale, and transform data if pathway/metabolite decrease
                # metabolite_raw is not normalized
                if self._pathway == 'Gi' or self._pathway == 'Gz(Gi)':
                    metabolite='cAMP'
                    metabolite_conc_raw=[]
                    for i in range(len(self._lig_conc_range)):
                        n=np.amax(self.simulation_data[ligand]['sim_data'][i]['obs_'+metabolite]) #cad
                        metabolite_conc_raw.append(n)
                    metabolite_conc_norm = minmax_scale(1-np.array(metabolite_conc_raw))
                elif self._pathway == 'Gs':
                    metabolite='cAMP'
                    metabolite_conc_raw=[]
                    for i in range(len(self._lig_conc_range)):
                        n=np.amax(self.simulation_data[ligand]['sim_data'][i]['obs_'+metabolite]) #cad
                        metabolite_conc_raw.append(n)
                    metabolite_conc_norm = minmax_scale(np.array(metabolite_conc_raw))
                elif self._pathway == 'Gq':
                    metabolite='IP3'
                    metabolite_conc_raw=[]
                    for i in range(len(self._lig_conc_range)):
                        n=np.amax(self.simulation_data[ligand]['sim_data'][i]['obs_'+metabolite]) #cad
                        metabolite_conc_raw.append(n)
                    metabolite_conc_norm = minmax_scale(np.array(metabolite_conc_raw))
                else: raise Exception('Unvailable Pathway. Please, introduce it manually. Networs available: "Gs", "Gi", "Gq".')


                ## save results
                raw_data_dict['x']=self._lig_conc_range
                raw_data_dict['y']=metabolite_conc_raw
                raw_data_dict['label']=self.simulation_data[ligand]['label']

                normalized_data_dict['x']=self._lig_conc_range
                normalized_data_dict['y']=metabolite_conc_norm
                normalized_data_dict['label']=self.simulation_data[ligand]['label']

                ## create a list of all data
                raw_data.append(raw_data_dict)
                normalized_data.append(normalized_data_dict)

                ##Fitting curve to the data

                def equation_dose(X, Bottom, Top, EC50, p):
                    return Bottom + (Top-Bottom)/(1+np.power((EC50/X),p))

                popt_IC50, pcov = curve_fit(equation_dose, self._lig_conc_range, metabolite_conc_norm, bounds=([np.min(metabolite_conc_norm),-np.inf,-np.inf, 0.5],[np.inf,np.max(metabolite_conc_norm),np.inf, 2.5]))

                xfit_IC50 = np.geomspace(lig_conc_min, lig_conc_max, 50000) # These values are the same as the values for the simulation time and not ligand concentration
                yfit_IC50 = equation_dose(xfit_IC50, *popt_IC50)

                fit_IC50={'x':xfit_IC50, 'y':yfit_IC50, 'label':self.simulation_data[ligand]['label']}




                dose[ligand] = {'raw_data': raw_data_dict,
                                'normalized_data':normalized_data_dict ,
                                'fitted_data': fit_IC50,
                                'IC50 (μM)': round(popt_IC50[2],5),
                                'pIC50': round(-np.log10(popt_IC50[2]*1E-6),2)}

            self.processed_data=dose
            return 

        def Curve(self, save=False, filename=None):
            '''
            Plot the dose-response curve.
            '''
            #dependencies
            if self.processed_data == None: raise TypeError('Simulation data unprocessed. simulation.inhibition.analysis() must be run first.')

            import plotly
            import plotly.graph_objs as go
            import plotly.offline as pyoff

            colors = plotly.colors.DEFAULT_PLOTLY_COLORS

            plot_data=[]

            color_id=0
            for ligand in self.processed_data:
                trace_norm = go.Scatter(x=self.processed_data[ligand]['normalized_data']['x'],
                                        y=minmax_scale(self.processed_data[ligand]['normalized_data']['y'])*100 ,
                                        mode='markers',
                                        showlegend=True,
                                        name=self.processed_data[ligand]['normalized_data']['label'],
                                        marker=dict(color=colors[color_id]))
                plot_data.append(trace_norm)

                trace_fitted = go.Scatter(x=self.processed_data[ligand]['fitted_data']['x'],
                                    y=minmax_scale(self.processed_data[ligand]['fitted_data']['y'])*100,
                                    mode='lines',
                                    showlegend=False,
                                    name=self.processed_data[ligand]['fitted_data']['label'],
                                    line=dict(color=colors[color_id]))
                plot_data.append(trace_fitted)
                color_id +=1

            layout = dict(title = '',
                            xaxis = dict(
                                title = '[ligand] μM',
                                type ='log',
                                #range = [-4, 2],
                                exponentformat='e',
                                titlefont=dict(
                                    size=20
                                ),
                                tickfont=dict(
                                    size=20
                                )),
                            yaxis = dict(
                                title = '% Response',
                                #range = [0, 100],
                                titlefont=dict(
                                    size=20),
                                tickfont=dict(
                                size=20)

                            ),
                            legend=dict(font=dict(size=15)),
                            autosize=False,
                            width=850,
                            height=650,
                            )

            fig = go.Figure(data=plot_data, layout=layout)
            if save==True:
                if filename==None: 
                    filename='plot.html'
                    return pyoff.plot(fig, filename=filename)
                else:
                    ext = os.path.splitext(filename)[-1]
                    if ext == '.png': fig.write_image(filename, scale=3)
                    elif ext == '.html': pyoff.plot(fig, filename=filename)
                    else: raise TypeError("extension not valid. Use png or html.")
            elif save ==False: return fig
            return 

        def constants(self):
            '''
            Returns the potency values.
            '''

            #dependencies
            if self.processed_data == None: raise TypeError('Simulation data unprocessed. simulation.activation.analysis() must be run first.')
            
            kvalues={}
            for ligand in self.processed_data:
                IC50 = list(self.processed_data[ligand].keys())[-2]
                IC50_value = self.processed_data[ligand][IC50]
                pIC50 = list(self.processed_data[ligand].keys())[-1]
                pIC50_value = self.processed_data[ligand][pIC50]
                kvalues[ligand]={IC50:IC50_value, pIC50:pIC50_value}
            self.constants = kvalues
            return kvalues 

        def PotencyToDict(self):
            '''
            Convert potencies into a dictionary.
            '''
            #dependencies
            if self.processed_data == None: raise TypeError('Simulation data unprocessed. simulation.inhibition.analysis() must be run first.')

            kvalues={}
            for ligand in self.processed_data:
                IC50 = list(self.processed_data[ligand].keys())[-2]
                IC50_value = self.processed_data[ligand][IC50]
                pIC50 = list(self.processed_data[ligand].keys())[-1]
                pIC50_value = self.processed_data[ligand][pIC50]
                kvalues[ligand]={IC50:IC50_value, pIC50:pIC50_value}
            return kvalues
        
        def Potency(self):
            '''
            Return the potency values as a pandas DataFrame.
            '''
            import pandas as pd
            data = simulation.inhibition.PotencyToDict(self)
            df = pd.DataFrame.from_dict(data, orient='index')
            return df

        def PotencyToCSV(self, path):
            '''
            Exports the potency values into csv format.

            :parameter path: Required (kwarg str): directory path to save the csv file
            '''
            data = simulation.inhibition.PotencyToDict(self)
            df = pd.DataFrame.from_dict(data, orient='index')
            df.to_csv(path, index=False)
            return

    class fitModel:
        """
        Fit a model to experimental data.

        .. note:: This class was developed to reproduce data from a specific experimental setup. Please see tutorial 4 (OXTR pathay). Use carefully!
        """
        def __init__(self):
        
            #fitting parameters
            self._expratio = None
            self._seed = None
            self._maxiter = None
            self._seed_incrementor = None
            self._target_parameter = None
            
            #Pathway parameters
            self._ttotal = None
            self._nsteps = None
            self._pathway = None
            self._observable = None
            self.pathway_parameters = {}
            
        def SetSimulationParameters(self, **kwargs):
            """
            :parameter pathway_parameters: Required (kwargs): dict of pathway parameters
            :parameter pathway:            Required (kwargs str): name of the pathway ('Gs', 'Gi', 'Gq')
            :parameter ttotal:             Required (kwargs int): simulation time (seconds)
            :parameter nsteps:             Required (kwargs int): simulation time step
            :parameter observable:         Required (kwargs str): molecular specie to be measured

            :return: instances of all parameters
                        
            """

            if 'pathway_parameters' in kwargs: 
                self.pathway_parameters = kwargs.pop('pathway_parameters')
                #print('pathway_parameters YES')
            self._DefaultPathwayParametersDataFrame=pd.DataFrame()
            if 'ttotal' in kwargs: 
                self._ttotal = int(kwargs.pop('ttotal'))
                print('ttotal =', self._ttotal)
            else: raise TypeError("ttotal undefined.")
                
            if 'nsteps' in kwargs: 
                self._nsteps = int(kwargs.pop('nsteps', 1000))
                print('nsteps =', self._nsteps)
            
            if 'pathway' in kwargs: 
                self._pathway = str(kwargs.pop('pathway'))
                print('pathway ->', self._pathway)
            else: raise TypeError("pathway undefined.")

            available_pathways = ['Gs', 'Gi', 'Gq', 'OXTR_pathway']
            if self._pathway == 'Gz(Gi)': self._pathway = 'Gi'
            if self._pathway not in available_pathways: raise Exception('Unvailable Pathway. Please, introduce it manually. Networs available: "Gs", "Gi", "Gq".')

            
            if'observable' in kwargs: 
                self._observable = str(kwargs.pop('observable'))
                print('observable ->', self._observable)
            else: raise TypeError("observable undefined.")
            
            return

        def PathwayParameters(self):
            """
            Display table with default pathway parameters.

            .. warning:: this functions requires the qgrid library. It doens't work on Google Colab.
            """
            import qgrid
            self._DefaultPathwayParametersDataFrame =  pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))

            col_opts = { 'editable': False, 'sortable':False}
            col_defs = {'Value': { 'editable': True, 'width': 150 }}
            self._DefaultPathwayParametersTable = qgrid.show_grid(self._DefaultPathwayParametersDataFrame, column_options=col_opts,column_definitions=col_defs)
            return self._DefaultPathwayParametersTable

        def UserPathwayParameters(self, path):
            """
            Import user pathway parameters.

            :parameter path:     Required (kwarg str): directory path
            """
            import qgrid
            self._DefaultPathwayParametersDataFrame =  pd.read_csv(path)
            col_opts = { 'editable': False, 'sortable':False}
            col_defs = {'Value': { 'editable': True, 'width': 150 }}
            self._DefaultPathwayParametersTable = qgrid.show_grid(self._DefaultPathwayParametersDataFrame, column_options=col_opts,column_definitions=col_defs)
            return self._DefaultPathwayParametersTable

        def PathwayParametersToCSV(self, path):
            """
            Export pathway parameters into CSV format.

            :parameter path:     Required (kwarg str): directory path
            """
            self._DefaultPathwayParametersTable.get_changed_df().to_csv(path, index=False)
            print('saved in:', path)
            return 

        def Reactions(self):
            """
            Display pathway reactions.
            """
            from IPython.display import display, HTML
            display(HTML("<style>.container {width:90% !important}</style>"))
            return pd.read_csv('src/lib/pathways/{}_reactions.csv'.format(self._pathway))
          
        def Run(self, **kwargs):
            """
            Fits of the model to experimental data.
            
            :parameter expratio:         Required (kwargs flt): experimental signalling specie concentration ratio
            :parameter target_parameter: Required (kwargs str):kinetic parameter to me modified
            :parameter maxiter:          Required (kwargs int): maximum number of iteration
            :parameter seed:             Required (kwargs flt): ramdom seed for scaling the modified parameter
            :parameter seed_incrementor: Required (kwargs flt): seed incrementor (each iteration will increment the seed by this value)
            :parameter seed_decrementor: Required (kwargs flt): seed decrementor (each iteration will decrement the seed by this value)
                        
            """

            from scipy.signal import find_peaks
            import decimal
            #fitting parameters
            if 'expratio' in kwargs: 
                self._expratio = float(kwargs.pop('expratio'))
                print('expratio =', self._expratio)
            else: raise TypeError("exratio undefined.")
                
            if 'seed' in kwargs: 
                self._seed = float(kwargs.pop('seed'))
                print('seed =', self._seed)
            else: raise TypeError("seed undefined.")
                
            if 'maxiter' in kwargs: 
                self._maxiter = int(kwargs.pop('maxiter', 100))
                print('maxiter =', self._maxiter)
    
            if 'seed_incrementor' in kwargs: 
                self._seed_incrementor = float(kwargs.pop('seed_incrementor', 0.1))
                print('seed_incrementor =', self._seed_incrementor)

            if 'seed_decrementor' in kwargs: 
                self._seed_decrementor = float(kwargs.pop('seed_decrementor', 0.1))
                print('seed_decrementor =', self._seed_decrementor)
                
            if 'target_parameter' in kwargs:
                self._target_parameter = str(kwargs.pop('target_parameter'))
                print('target_parameter ->', self._target_parameter)
            else: raise TypeError("target_parameter undefined.")
            
            
            #Get default pathway parameters            
            if  self._DefaultPathwayParametersDataFrame.empty and self.pathway_parameters==None:
                self._DefaultPathwayParametersDataFrame = pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))
                self._PathwayParameters = self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict()    

            elif self._DefaultPathwayParametersDataFrame.empty is False and self.pathway_parameters is None:
                try: 
                    #extract data from qgrid
                    newparameters = self._DefaultPathwayParametersTable.get_changed_df()
                    self._PathwayParameters = newparameters.set_index('Parameter').iloc[:,0].to_dict()
                except:
                    self._PathwayParameters = self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict()
            
            elif self._DefaultPathwayParametersDataFrame.empty and self.pathway_parameters is not None: 
                self._DefaultPathwayParametersDataFrame = pd.read_csv('src/lib/pathways/{}_parameters.csv'.format(self._pathway))
                self._PathwayParameters = {**self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict(), **self.pathway_parameters}

            elif self._DefaultPathwayParametersDataFrame.empty is False and self.pathway_parameters is not None:
                try: 
                    #extract data from qgrid
                    newparameters = self._DefaultPathwayParametersTable.get_changed_df()
                    self._PathwayParameters = {**newparameters.set_index('Parameter').iloc[:,0].to_dict(), **self.pathway_parameters}
                except:
                    self._PathwayParameters = {**self._DefaultPathwayParametersDataFrame.set_index('Parameter').iloc[:,0].to_dict(), **self.pathway_parameters}



            #simulation parameters:
            if not self._ttotal: 
                raise TypeError("simulation parameters unknown. Set the the simulation parameters first wiht set_simulation_parameters()")
            
            #Main function
            mypathway = importlib.import_module('.'+self._pathway, package='src.lib.pathways')
            self.simtime = pl.geomspace(0.00001, self._ttotal, num=self._nsteps) 

            #Simulation 1
            pathway_model = mypathway.network(LR=None, kinetics=True, **self._PathwayParameters)
            sim1 = ScipyOdeSimulator(pathway_model, tspan=self.simtime,compiler='cython').run()
            self.simres1 = sim1.all
                                
            def calc_ratio(self):
                
                
                #Simulation 2
                sim2 = ScipyOdeSimulator(mypathway.network(**self.new_pathway_parameters), tspan=self.simtime, compiler='cython').run()
                self.simres2 = sim2.all

                #analysis
                obs_name = 'obs_'+self._observable
                obs_1  = self.simres1[obs_name]
                obs_2  = self.simres2[obs_name]
                
                if 'time_in' in self.new_pathway_parameters:
                    self._time = np.take(self.simtime, np.where(self.simtime > int(self.new_pathway_parameters['time_in'])))[0]
                    obs_curve_1  = np.take(obs_1,  np.where(self.simtime > int(self.new_pathway_parameters['time_in'])))[0]
                    obs_curve_2  = np.take(obs_2, np.where(self.simtime > int(self.new_pathway_parameters['time_in'])))[0]
                                
                else:
                    self._time = np.take(self.simtime, np.where(self.simtime>0))[0]
                    obs_curve_1  = np.take(obs_1,  np.where(self.simtime > 0))[0]
                    obs_curve_2  = np.take(obs_2, np.where(self.simtime > 0))[0]
                        
                obs_peaks_1, _  = find_peaks(obs_curve_1)
                obs_peaks_2, _  = find_peaks(obs_curve_2)

                vmax_obs_curve_1  = obs_curve_1[obs_peaks_1][-1]*1E3
                vmax_obs_curve_2  = obs_curve_2[obs_peaks_2][-1]*1E3

                obs_ratio = round(vmax_obs_curve_2/vmax_obs_curve_1, abs(decimal.Decimal(str(self._expratio).rstrip('0')).as_tuple().exponent))

                self._obs_curve_1=obs_curve_1
                self._obs_curve_2=obs_curve_2
                self._obs_peaks_1=obs_peaks_1
                self._obs_peaks_2=obs_peaks_2
                self._vmax_obs_curve_1=vmax_obs_curve_1
                self._vmax_obs_curve_2=vmax_obs_curve_2

                return obs_ratio
        
            self._iteration=1
            print('\n')
            
            self._lst_ratio=[]
            self._lst_seed=[]
        
            for idx in range(self._maxiter):
                
                prefix = 'iteration'
                iteration_n = str(self._iteration)
                print(f'\r{prefix} {iteration_n}', end='\r')
                
                self.new_pathway_parameters={**self._PathwayParameters, **{self._target_parameter:mypathway.defaultParameters[self._target_parameter]*self._seed}}
                self.obs_ratio = calc_ratio(self)

                if self.obs_ratio == self._expratio:
                    self._lst_ratio.append(self.obs_ratio)
                    self._lst_seed.append(self._seed)
                    self._fold=round(self._seed, abs(decimal.Decimal(str(self._expratio).rstrip('0')).as_tuple().exponent))
                    print('\n\nDONE!\n', '\nRatio: '+str(self.obs_ratio), '\nFOLD: '+str(self._fold), '\nNumber of iterations: '+str(self._iteration))
                    break
                elif self.obs_ratio < self._expratio:
                    
                    self._lst_ratio.append(self.obs_ratio)
                    self._lst_seed.append(self._seed)
                    self._iteration+=1
                    self._seed += self._seed_incrementor     

                else:
                    self._lst_ratio.append(self.obs_ratio)
                    self._lst_seed.append(self._seed)


                    self._iteration+=1
                    self._seed -= self._seed_decrementor
    
            return

        def plotIterations(self, save=False, filename=None):
            '''
            Plot iterations. 
            '''
            import plotly.offline as pyoff
            #dependencies
            if self._iteration == None: raise TypeError('Simulation data not exist. simulation.fitModel.run() must be run first.')

            #import plotly
            import plotly.graph_objs as go

            iterations = np.arange(1,self._iteration+1)

            trace=dict(type='scatter', x=self._lst_seed, y=self._lst_ratio, mode='markers', 
                    marker=dict(color= iterations, colorscale='Bluered_r', size=14, colorbar=dict(thickness=20, title='iteration number')))
            #axis_style=dict(zeroline=False, showline=True, mirror=True)
            layout = dict(title = '',
                xaxis = dict(
                    title = 'seed',
                    titlefont=dict(
                        size=20
                    ),
                    tickfont=dict(
                        size=20
                    )),
                yaxis = dict(
                    title = '['+self._observable+']' + ' ratio',
                    titlefont=dict(
                        size=20),
                    tickfont=dict(
                    size=20)

                ),
                legend=dict(font=dict(size=15)),
                autosize=False,
                width=850,
                height=650
                )

            fig = go.Figure(data=[trace], layout=layout)
            if save==True:
                if filename==None: 
                    filename='plot.html'
                    return pyoff.plot(fig, filename=filename)
                else:
                    ext = os.path.splitext(filename)[-1]
                    if ext == '.png': fig.write_image(filename, scale=3)
                    elif ext == '.html': pyoff.plot(fig, filename=filename)
                    else: raise TypeError("extension not valid. Use png or html.")
            elif save ==False: return fig
            return fig

        def plotCurves(self, save=False, filename=None):
            '''
            Plot the amount of obeservable in function of time, Amplitude, Area Under the Curve, and Full Width at Half Maximum. 

            :parameter save:     Optional (kwarg boolean): default False
            :parameter filename: Optional (kwarg str)
            '''

            from IPython.core.display import display, HTML
            display(HTML("<style>.container { width:90% !important; }</style>"))


            from plotly.subplots import make_subplots
            from scipy.signal import peak_widths
            from sklearn import metrics
            import plotly.offline as pyoff


            half_1 = peak_widths(self._obs_curve_1, self._obs_peaks_1, rel_height=0.5)
            half_2 = peak_widths(self._obs_curve_2, self._obs_peaks_2, rel_height=0.5)
            fwhm_1 = self._time[int(half_1[3])]-self._time[int(half_1[2])]
            fwhm_2 = self._time[int(half_2[3])]-self._time[int(half_2[2])]


            fig = make_subplots(rows=2, cols=2,vertical_spacing=0.15,
                                subplot_titles=("{} concentration".format(self._observable), "Amplitude", "Area under the curve", "Full Width at Half Maximum"))

            ####################
            #### MAIN PLOT  ####
            ####################
            fig.add_trace(go.Scatter(x=self._time, y=self._obs_curve_1*1E3, name='control'), row=1, col=1)
            fig.add_trace(go.Scatter(x=self._time, y=self._obs_curve_2*1E3, name='{}-fold'.format(self._fold)), row=1, col=1)
            fig.add_trace(go.Scatter(x=self._time[self._obs_peaks_1], y=self._obs_curve_1[self._obs_peaks_1]*1E3,
                                    name='max value', showlegend=False, mode='markers', 
                                    marker=dict(symbol='x', size=13, color='Black')), row=1,col=1)
            fig.add_trace(go.Scatter(x=self._time[self._obs_peaks_2], y=self._obs_curve_2[self._obs_peaks_2]*1E3,
                                    name='max value', showlegend=False, mode='markers', 
                                    marker=dict(symbol='x', size=13, color='Black')), row=1,col=1)
            fig.add_shape(type='line', x0=self._time[int(half_1[2])],y0=half_1[1][0]*1E3, x1=self._time[int(half_1[3])], y1=half_1[1][0]*1E3,
                        line=dict(color='Blue',dash='dash'),xref='x',yref='y', row=1, col=1)
            fig.add_shape(type='line', x0=self._time[int(half_2[2])],y0=half_2[1][0]*1E3, x1=self._time[int(half_2[3])], y1=half_2[1][0]*1E3,
                        line=dict(color='Red',dash='dash'),xref='x',yref='y', row=1, col=1)

            # Update xaxis properties
            fig.update_xaxes(title_text="Time (s)", showgrid=False, row=1, col=1, titlefont=dict(size=18), 
                            linecolor='black', linewidth=2,
                            ticks='inside', tickfont=dict(size=18), tickcolor='black', ticklen=10, tickwidth=2)

            fig.update_yaxes(title_text=self._observable+' (nM)', titlefont=dict(size=18), showgrid=False, row=1, col=1, 
                            linecolor='black', linewidth=2,
                            ticks='inside', tickfont=dict(size=18), tickcolor='black', ticklen=10, tickwidth=2)


            ####################
            #### AMPLITUDE  ####
            ####################

            AMP_labels = [1,2]
            AMP_values = [self._vmax_obs_curve_1, self._vmax_obs_curve_2]
            fig.add_trace(go.Bar(x=AMP_labels,y=AMP_values, width = [0.35,0.35], showlegend=False, marker_color='black', name=''), row=1, col=2 )

                

            # Update xaxis properties
            fig.update_xaxes(row=1, col=2, showgrid=False, linecolor='black', linewidth=2, range=[0,3],
                            tickmode='array', tickvals=[1,2], ticktext=['control', '{}-fold'.format(self._fold)], tickfont=dict(size=18))

            fig.update_yaxes(showgrid=False, range=[round((min(AMP_values)-min(AMP_values)*0.5)/5)*5,round((max(AMP_values)+max(AMP_values)*0.5)/5)*5 ], row=1, col=2,
                            title_text=self._observable+' (nM)', titlefont=dict(size=18),
                            linecolor='black', linewidth=2, ticks='inside', ticklen=10, tickwidth=2, tickfont=dict(size=18))

            # Add diff lines
            AMP_diffs = [max(AMP_values) - v for v in AMP_values]
            AMP_diff_labels = dict(zip(AMP_labels, AMP_diffs))
            fig.add_trace(go.Scatter(name='',x=[1,1.5,2], y=[max(AMP_values)+(max(AMP_values)*0.3)]*3, mode = 'lines+text',showlegend=False, line=dict(color='black', width=1),text=['', 'diff. = {} nM'.format(round(AMP_diffs[0], 3)),''], textposition='top center'), row=1, col=2)
            fig.add_trace(go.Scatter(name='',x=[AMP_labels[0]-0.175, AMP_labels[0]+0.175], y=[AMP_values[0]+(AMP_values[0]*0.03)]*2, mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=1, col=2)
            fig.add_trace(go.Scatter(name='',x=[AMP_labels[1]-0.175, AMP_labels[1]+0.175], y=[AMP_values[1]+(AMP_values[1]*0.03)]*2, mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=1, col=2)
            fig.add_trace(go.Scatter(name='',x=[AMP_labels[0], AMP_labels[0]], y=[AMP_values[0]+(AMP_values[0]*0.03), max(AMP_values)+(max(AMP_values)*0.3)], mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=1, col=2)
            fig.add_trace(go.Scatter(name='',x=[AMP_labels[1], AMP_labels[1]], y=[AMP_values[1]+(AMP_values[1]*0.03), max(AMP_values)+(max(AMP_values)*0.3)], mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=1, col=2)
            

            ####################
            ####     AUC    ####
            ####################

            # Data
            AUC_labels = [1,2]
            AUC_values = [round(metrics.auc(self._time, self._obs_curve_1),2), round(metrics.auc(self._time, self._obs_curve_2),2)]
            fig.add_trace(go.Bar(x=AUC_labels,y=AUC_values, width = [0.35,0.35], showlegend=False, marker_color='black', name=''), row=2, col=1 )
                    
            # Update xaxis properties
            fig.update_xaxes(row=2, col=1, tickmode='array', showgrid=False, range=[0,3], linecolor='black', linewidth=2,
                            tickvals=[1,2], ticktext=['control', '{}-fold'.format(self._fold)], tickfont=dict(size=18))

            fig.update_yaxes(row=2, col=1,showgrid=False,  title_text=self._observable+' (nM)', range=[round((min(AUC_values)-min(AUC_values)*0.5)/5)*5,round((max(AUC_values)+max(AUC_values)*0.5)/5)*5], 
                            titlefont=dict(size=18),linecolor='black', linewidth=2, 
                            ticks='inside', tickfont=dict(size=18),ticklen=10, tickwidth=2)

            # Add diff lines
            AUC_diffs = [max(AUC_values) - v for v in AUC_values]
            AUC_diff_labels = dict(zip(AUC_labels, AUC_diffs))
            fig.add_trace(go.Scatter(name='',x=[1,1.5,2], y=[max(AUC_values)+(max(AUC_values)*0.3)]*3, mode = 'lines+text',showlegend=False, 
                                    line=dict(color='black', width=1), text=['', 'diff. = {} nM'.format(round(AUC_diffs[0], 3)),''], textposition='top center'), row=2, col=1)
            fig.add_trace(go.Scatter(name='',x=[AUC_labels[0]-0.175, AUC_labels[0]+0.175], y=[AUC_values[0]+(AUC_values[0]*0.03)]*2, mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=1)
            fig.add_trace(go.Scatter(name='',x=[AUC_labels[1]-0.175, AUC_labels[1]+0.175], y=[AUC_values[1]+(AUC_values[1]*0.03)]*2, mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=1)
            fig.add_trace(go.Scatter(name='',x=[AUC_labels[0], AUC_labels[0]], y=[AUC_values[0]+(AUC_values[0]*0.03), max(AUC_values)+(max(AUC_values)*0.3)], mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=1)
            fig.add_trace(go.Scatter(name='',x=[AUC_labels[1], AUC_labels[1]], y=[AUC_values[1]+(AUC_values[1]*0.03), max(AUC_values)+(max(AUC_values)*0.3)], mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=1)


            ####################
            ####    FWHM    ####
            ####################
            # Data
            FWHM_labels = [1,2]
            FWHM_values = [fwhm_1, fwhm_2]
            fig.add_trace(go.Bar(x=FWHM_labels,y=FWHM_values, width = [0.35,0.35], showlegend=False,marker_color='black', name=''), row=2, col=2 )
            
            # Update xaxis properties
            fig.update_xaxes(row=2, col=2, showgrid=False, range=[0,3], linecolor='black', linewidth=2, 
                            tickmode='array', tickvals=[1,2], ticktext=['control', '{}-fold'.format(self._fold)], tickfont=dict(size=18))

            fig.update_yaxes(row=2, col=2, showgrid=False, range=[self.pathway_parameters['time_in'],round((max(FWHM_values)+(max(FWHM_values)-self.pathway_parameters['time_in'])*0.5)/5)*5], 
                            title_text='Time (s)', titlefont=dict(size=18), linecolor='black', linewidth=2,
                            ticks='inside', ticklen=10, tickwidth=2, tickfont=dict(size=18))

            # Add diff lines
            FWHM_diffs = [max(FWHM_values) - v for v in FWHM_values]
            FWHM_diff_labels = dict(zip(FWHM_labels, FWHM_diffs))
            line_height = max(FWHM_values)+((max(FWHM_values)-self.pathway_parameters['time_in'])*0.30)
            fig.add_trace(go.Scatter(x=[1,1.5,2], y=[line_height]*3, mode = 'lines+text',showlegend=False, line=dict(color='black', width=1),name='',
                                    text=['', 'diff. = {} s'.format(round(FWHM_diffs[0], 3)),''], textposition='top center'), row=2, col=2)
            fig.add_trace(go.Scatter(name='',x=[FWHM_labels[0]-0.175, FWHM_labels[0]+0.175], y=[FWHM_values[0]+(FWHM_values[0]*0.005)]*2, mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=2)
            fig.add_trace(go.Scatter(name='',x=[FWHM_labels[1]-0.175, FWHM_labels[1]+0.175], y=[FWHM_values[1]+(FWHM_values[1]*0.005)]*2, mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=2)
            fig.add_trace(go.Scatter(name='',x=[FWHM_labels[0], FWHM_labels[0]], y=[FWHM_values[0]+(FWHM_values[0]*0.005), line_height], mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=2)
            fig.add_trace(go.Scatter(name='',x=[FWHM_labels[1], FWHM_labels[1]], y=[FWHM_values[1]+(FWHM_values[1]*0.005), line_height], mode = 'lines',showlegend=False, line=dict(color='black', width=1)), row=2, col=2)


            ####################
            ####   FIGURE   ####
            ####################

            fig.update_layout(height=1200, width=1300, title_text="", plot_bgcolor='white',showlegend=True, 
                            legend=dict(yanchor="top", x=0.3, y=.99,font=dict(family="sans-serif", size=14,color="black")))
            fig.update_annotations(font_size=20, font_color='black')
            
            if save==True:
                if filename==None: 
                    filename='plot.html'
                    return pyoff.plot(fig, filename=filename)
                else:
                    ext = os.path.splitext(filename)[-1]
                    if ext == '.png': fig.write_image(filename, scale=3)
                    elif ext == '.html': pyoff.plot(fig, filename=filename)
                    else: raise TypeError("extension not valid. Use png or html.")
            elif save ==False: return fig
            
            return

