##################################################
##  Description:
##  This file aims to provide the model solution for the 
##  example in Chen, Hansen and Hansen (forthcoming paper). Advanced users
##  can modify the Python code to accomodate other examples.
##################################################
##  Any questions/suggestions, please contact
##  Han Xu:  hanxuh@uchicago.edu
##  Zhenhuan Xie: zhenhuanxie@uchicago.edu
##################################################

import numpy as np
import pandas as pd
from numba import jit
from scipy.optimize import minimize


'''
Objective function and its gradient. Use numba.jit to boost computational performance.
'''
@jit
def _objective_numba(f,g,pd_lag_indicator,pd_indicator_float,state,n_f,e,ξ,λ):     
    selector = pd_lag_indicator[:,state-1]
    term_1 = -g[selector]/ξ
    term_2 = f[:,(state-1)*n_f:state*n_f][selector]@λ
    term_3 = np.log(pd_indicator_float[selector]@e)
    x = term_1 + term_2 + term_3
    # Use "max trick" to improve accuracy
    a = x.max()
    # log_E_exp(x)
    return np.log(np.mean(np.exp(x-a))) + a    

@jit
def _objective_gradient_numba(f,g,pd_lag_indicator,pd_indicator_float,state,n_f,e,ξ,λ):      
    selector = pd_lag_indicator[:,state-1]
    temp1 = -g[selector]/ξ + f[:,(state-1)*n_f:state*n_f][selector]@λ + np.log(pd_indicator_float[selector]@e)
    temp2 = f[:,(state-1)*n_f:state*n_f][selector]*(np.exp(temp1.reshape((len(temp1),1)))/np.mean(np.exp(temp1)))
    temp3 = np.empty(temp2.shape[1])
    for i in range(temp2.shape[1]):
        temp3[i] = np.mean(temp2[:,i])
    return temp3


'''
Solver for the intertemporal divergence problem. Here we use relative entropy as the measure of divergence.
'''
class InterDivConstraint:
    def __init__(self,n_states,tol=1e-8,max_iter=1000):
        """
        Load datasets and initialize the solver.
        """        
        # Load data
        data = pd.read_csv('./data/UnitaryData.csv')
        pd_lag = np.array(data['d.p'])
        
        # Specify dimensions
        self.n_f = 4
        self.n_states = n_states
        
        # Calculate indicator based on today's pd ratio
        pd_lag_indicator_float = np.empty((data.shape[0], self.n_states))
        tercile = np.quantile(pd_lag, np.arange(self.n_states + 1)/self.n_states)
        for i in range(self.n_states):
            pd_lag_indicator_float[:,i] = (pd_lag >= tercile[i]) & (pd_lag <= tercile[i+1])
        pd_lag_indicator = pd_lag_indicator_float.astype(bool)
        
        # Calculate indicator for tomorrow's pd ratio
        self.pd_indicator = pd_lag_indicator[1:]
        self.pd_indicator_float = self.pd_indicator.astype(float)
        
        # Drop last row since we do not have tomorrow's pd ratio at that point
        self.pd_lag_indicator = pd_lag_indicator[:-1]
        self.X = np.array(data[['Rf','Rm-Rf','SMB','HML']])[:-1]
        self.f = np.empty((self.X.shape[0], self.X.shape[1] * self.n_states))
        for i in range(self.n_states):
            self.f[:,(self.n_f * i):(self.n_f * (i+1))] = self.X * self.pd_lag_indicator[:,(i):(i+1)]
        self.log_Rw = np.array(data['log.RW'])[:-1] 
        
        # Placeholder for g,state, e, ϵ
        self.g = None
        self.state = None
        self.e = None
        self.ϵ = None
        
        # Specify tolerance levels and maximum iterations for the convex solver
        self.tol = tol
        self.max_iter = max_iter
        
    def _objective(self,λ):
        """
        Objective function of the minimization problem.
        """
        if self.lower:
            return _objective_numba(self.f,self.g,self.pd_lag_indicator,self.pd_indicator_float,self.state,self.n_f,self.e,self.ξ,λ)
        else:
            return _objective_numba(self.f,-self.g,self.pd_lag_indicator,self.pd_indicator_float,self.state,self.n_f,self.e,self.ξ,λ)            
    
    def _objective_gradient(self,λ):
        """
        Gradient of the objective function.     
        """
        if self.lower:
            return _objective_gradient_numba(self.f,self.g,self.pd_lag_indicator,self.pd_indicator_float,self.state,self.n_f,self.e,self.ξ,λ)
        else:
            return _objective_gradient_numba(self.f,-self.g,self.pd_lag_indicator,self.pd_indicator_float,self.state,self.n_f,self.e,self.ξ,λ)            
    
    def _min_objective(self):
        """
        Use scipy.minimize (L-BFGS-B, BFGS or CG) to solve the minimization problem.
        """
        for method in ['L-BFGS-B','BFGS','CG']:
            model = minimize(self._objective, 
                             np.ones(self.n_f), 
                             method = method,
                             jac = self._objective_gradient,
                             tol = self.tol,
                             options = {'maxiter': self.max_iter})
            if model.success:
                break
        if model.success == False:
            print("---Warning: the convex solver fails when ξ = %s, tolerance = %s--- " % (self.ξ,self.tol))
            print(model.message)
            
        # Calculate v and λ (here λ is of dimension self.n_f)
        v = np.exp(model.fun)
        λ = model.x
        return v,λ
    
    
    def iterate(self,ξ,lower=True):
        """
        Iterate to get staitionary e and ϵ (eigenvector and eigenvalue) for the minimization problem. Here we fix ξ.
        Return a dictionary of variables that are of our interest. 
        """
        # Check if self.g is defined or not
        if self.g is None:
            raise Exception("Sorry, please define self.g first!")            
        
        # Fix ξ
        self.ξ = ξ
        self.lower = lower
        
        # Initial error
        error = 1.
        # Count iteration times
        count = 0

        while error > self.tol:
            if count == 0:
                # initial guess for e
                self.e = np.ones(self.n_states)
                # placeholder for v
                v = np.zeros(self.n_states)   
                # placeholder for λ
                λ = np.zeros(self.n_states*self.n_f)
            for k in np.arange(1,self.n_states+1,1):
                self.state = k
                v[self.state-1],λ[(self.state-1)*self.n_f:self.state*self.n_f] = self._min_objective()
            # update e and ϵ
            e_old = self.e
            self.ϵ = v[0]
            self.e = v/v[0]
            error = np.max(np.abs(self.e - e_old))
            count += 1
        
        # Calculate N and E[N|state k]
        if self.lower:
            N = 1./self.ϵ * np.exp(-self.g/self.ξ+self.f@λ) * (self.pd_indicator@self.e) / (self.pd_lag_indicator@self.e)
        else:
            N = 1./self.ϵ * np.exp(self.g/self.ξ+self.f@λ) * (self.pd_indicator@self.e) / (self.pd_lag_indicator@self.e)
        E_N_cond = []
        for i in np.arange(1,self.n_states+1,1):
            temp = np.mean(N[self.pd_lag_indicator[:,i-1]])
            E_N_cond.append(temp)
        E_N_cond = np.array(E_N_cond)
        
        # Calculate transition matrix and staionary distribution under distorted probability
        P_tilde = np.zeros((self.n_states,self.n_states))
        for i in np.arange(1,self.n_states+1,1):
            for j in np.arange(1,self.n_states+1,1):
                P_tilde[i-1,j-1] = np.mean(N[self.pd_lag_indicator[:,i-1]]*self.pd_indicator[self.pd_lag_indicator[:,i-1]][:,j-1]) 
        A = P_tilde.T - np.eye(self.n_states)
        A[-1] = np.ones(self.n_states)
        B = np.zeros(self.n_states)
        B[-1] = 1.
        π_tilde = np.linalg.solve(A, B)
        
        # Calculate transition matrix and stationary distribution under the original empirical probability
        P = np.zeros((self.n_states,self.n_states))
        for i in np.arange(1,self.n_states+1,1):
            for j in np.arange(1,self.n_states+1,1):
                P[i-1,j-1] = np.mean(self.pd_indicator[self.pd_lag_indicator[:,i-1]][:,j-1]) 
        A = P.T - np.eye(self.n_states)
        A[-1] = np.ones(self.n_states)
        B = np.zeros(self.n_states)
        B[-1] = 1.
        π = np.linalg.solve(A, B)
        
        # Calculate conditional/unconditional 
        RE_cond = []
        for i in np.arange(1,self.n_states+1,1):
            temp = np.mean(N[self.pd_lag_indicator[:,i-1]]*np.log(N[self.pd_lag_indicator[:,i-1]]))
            RE_cond.append(temp)
        RE_cond = np.array(RE_cond)
        RE = RE_cond @ π_tilde
        
        # Calculate μ and moment bound
        μ = - self.ξ * np.log(self.ϵ)
        moment_bound_check = μ - self.ξ*RE
        # Conditional moment bounds
        moment_bound_cond = []
        for i in np.arange(1,self.n_states+1,1):
            temp = np.mean(N[self.pd_lag_indicator[:,i-1]]*self.g[self.pd_lag_indicator[:,i-1]])
            moment_bound_cond.append(temp)
        moment_bound_cond = np.array(moment_bound_cond)
        moment_bound = moment_bound_cond @ π_tilde
        
        # Calculate the original conditional/unconditional moment for g(X)
        # Original moment 
        moment_cond = []
        for i in np.arange(1,self.n_states+1,1):
            temp = np.mean(self.g[self.pd_lag_indicator[:,i-1]])
            moment_cond.append(temp)  
        moment = np.mean(self.g)
        
        # Calculate v
        v_0 = -self.ξ * np.log(self.e)
        
        result = {'ϵ':self.ϵ,
                  'e':self.e,
                  'λ':λ,
                  'count':count,
                  'ξ':self.ξ,
                  'μ':μ,
                  'v_0':v_0,
                  'RE_cond':RE_cond,
                  'RE':RE,
                  'E_N_cond':E_N_cond,
                  'P':P,
                  'π':π,
                  'P_tilde':P_tilde,
                  'π_tilde':π_tilde,
                  'moment_bound':moment_bound,
                  'moment_bound_check':moment_bound_check,
                  'moment_bound_cond':moment_bound_cond,
                  'moment_cond':moment_cond,
                  'moment':moment,
                  'N':N}
        
        return result
    
    
    def find_ξ(self,x_min_RE,lower,tol=1e-7,max_iter=100,upper_bound=100.):
        """
        This function will use bisection method to find the ξ that corresponds to x times the minimal RE.
        """
        # Get minimal RE
        result = self.iterate(100.,lower)
        min_RE = result['RE']
        
        # Start iteration
        count = 0
        for i in range(max_iter):
            # Get RE at current choice of ξ
            if i == 0:
                ξ = 1.
                # Set lower/upper bounds for ξ
                lower_bound = 0.
                upper_bound = upper_bound
                
            result = self.iterate(ξ,lower)
            RE = result['RE']
            
            # Compare to the level we want
            error = RE/min_RE-x_min_RE
            if np.abs(error)<tol:
                break
            else:
                if error < 0.:
                    upper_bound = ξ
                    ξ = (lower_bound + ξ)/2.
                else:
                    lower_bound = ξ
                    ξ = (ξ + upper_bound)/2.
            
            count += 1
            if count == max_iter:
                print('Maximal iterations reached. Error = %s' % (RE/min_RE-x_min_RE))
        
        return ξ
    
      

'''
Below are helper functions that find the lower/upper bounds for the proportional risk premium.
'''
        
def risk_premia(n_states,ζ,x_min_RE,lower,ξ_tol=1e-7):
    # Initialize the solver
    solver = InterDivConstraint(n_states=n_states,tol=1e-9,max_iter=1000)

    # Define g(X) = Rw - ζ*Rf
    g1 = np.exp(solver.log_Rw)
    g2 = (solver.X[:,0]+1.)*np.exp(solver.log_Rw)

    solver.g = g1 - ζ*g2

    # Find ξ that corresponds to x min RE
    ξ = solver.find_ξ(x_min_RE=x_min_RE,lower=lower,tol=ξ_tol,max_iter=100)

    # Solve models with the chosen ξ
    result = solver.iterate(ξ,lower=lower)

    # Calculate risk premia, empirical
    # Term 1
    moment_cond_g1 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(g1[solver.pd_lag_indicator[:,i-1]])
        moment_cond_g1.append(temp)
    moment_cond_g1 = np.array(moment_cond_g1)
    moment_g1 = moment_cond_g1@result['π']
    
    # Term 2
    moment_cond_g2 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(g2[solver.pd_lag_indicator[:,i-1]])
        moment_cond_g2.append(temp)
    moment_cond_g2 = np.array(moment_cond_g2)
    moment_g2 = moment_cond_g2@result['π']
    
    # Combine term 1 and term 2
    risk_premia_empirical = np.log(moment_g1) - np.log(moment_g2)
    risk_premia_cond_empirical = np.log(moment_cond_g1) - np.log(moment_cond_g2)
    
    # Calculate risk premia, distorted
    # Term 1
    moment_bound_cond_g1 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(result['N'][solver.pd_lag_indicator[:,i-1]]*g1[solver.pd_lag_indicator[:,i-1]])
        moment_bound_cond_g1.append(temp)
    moment_bound_cond_g1 = np.array(moment_bound_cond_g1)
    moment_bound_g1 = moment_bound_cond_g1@result['π_tilde']
    
    # Term 2
    moment_bound_cond_g2 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(result['N'][solver.pd_lag_indicator[:,i-1]]*g2[solver.pd_lag_indicator[:,i-1]])
        moment_bound_cond_g2.append(temp)
    moment_bound_cond_g2 = np.array(moment_bound_cond_g2)
    moment_bound_g2 = moment_bound_cond_g2@result['π_tilde']
    
    # Combine term 1 and term 2
    risk_premia = np.log(moment_bound_g1) - np.log(moment_bound_g2)
    risk_premia_cond = np.log(moment_bound_cond_g1) - np.log(moment_bound_cond_g2)    
    return risk_premia, risk_premia_cond, risk_premia_empirical, risk_premia_cond_empirical

   
    
'''
Below are helper functions that find the lower/upper bounds for the volatility.
'''
        
def volatility(n_states,ζ,x_min_RE,lower,ξ_tol=1e-7):
    # Initialize the solver
    solver = InterDivConstraint(n_states=n_states,tol=1e-9,max_iter=1000)

    # Define g(X) = Rw - ζ*log Rw
    g1 = np.exp(solver.log_Rw)
    g2 = solver.log_Rw

    solver.g = g1 - ζ*g2

    # Find ξ that corresponds to x min RE
    ξ = solver.find_ξ(x_min_RE=x_min_RE,lower=lower,tol=ξ_tol,max_iter=100)

    # Solve models with the chosen ξ
    result = solver.iterate(ξ,lower=lower)

    # Calculate volatility, empirical
    # Term 1
    moment_cond_g1 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(g1[solver.pd_lag_indicator[:,i-1]])
        moment_cond_g1.append(temp)
    moment_cond_g1 = np.array(moment_cond_g1)
    moment_g1 = moment_cond_g1@result['π']
    
    # Term 2
    moment_cond_g2 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(g2[solver.pd_lag_indicator[:,i-1]])
        moment_cond_g2.append(temp)
    moment_cond_g2 = np.array(moment_cond_g2)
    moment_g2 = moment_cond_g2@result['π']
    
    # Combine term 1 and term 2
    vol_empirical = np.log(moment_g1) - moment_g2
    vol_cond_empirical = np.log(moment_cond_g1) - moment_cond_g2
    
    # Calculate volatility, distorted
    # Term 1
    moment_bound_cond_g1 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(result['N'][solver.pd_lag_indicator[:,i-1]]*g1[solver.pd_lag_indicator[:,i-1]])
        moment_bound_cond_g1.append(temp)
    moment_bound_cond_g1 = np.array(moment_bound_cond_g1)
    moment_bound_g1 = moment_bound_cond_g1@result['π_tilde']
    
    # Term 2
    moment_bound_cond_g2 = []
    for i in np.arange(1,solver.n_states+1,1):
        temp = np.mean(result['N'][solver.pd_lag_indicator[:,i-1]]*g2[solver.pd_lag_indicator[:,i-1]])
        moment_bound_cond_g2.append(temp)
    moment_bound_cond_g2 = np.array(moment_bound_cond_g2)
    moment_bound_g2 = moment_bound_cond_g2@result['π_tilde']
    
    # Combine term 1 and term 2
    vol = np.log(moment_bound_g1) - moment_bound_g2
    vol_cond = np.log(moment_bound_cond_g1) - moment_bound_cond_g2   
    return vol, vol_cond, vol_empirical, vol_cond_empirical


