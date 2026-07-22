# INTELLIGENCE FROM LEARNABLE NOVELTY

A PREPRINT

Yanbo Zhang <sup>1</sup> Michael Levin <sup>1,2†</sup>

<sup>1</sup> Allen Discovery Center at Tufts University, Medford, MA, 02155, USA <sup>2</sup> Wyss Institute for Biologically Inspired Engineering at Harvard University, Boston, MA, 02115, USA

July 22, 2026

## ABSTRACT

Intelligence appears under different names in different fields: as data compression in statistics and machine learning, as universal computation in dynamical systems, and as adaptive behavior in agents. Each field carries its own objective, and the two most influential drives often fail in mirror image: novelty search, which seeks surprise, is transfixed by a noisy television screen, while the free-energy principle, which avoids surprise, is most content in a dark room. Both failures have a single cause: each objective treats as one quantity the surprise a learner can convert into knowledge and the surprise it never can. Here we show that the learnable part of that information, which we call learnable novelty, yields the seemingly disparate projections of intelligence, and we give a closedform estimator of it built on a cheap and differentiable reservoir computer. Used as a measure, with no supervision of any kind, the estimator recovers decades of complexity classification, ranking the Turing-complete rule 110 highest among the elementary cellular automata. Used as an objective, its gradient carries a neural cellular automaton from simple dynamics into a regime of solitons, the traveling, colliding structures by which rule 110 computes, as well as organizes the representation of an image encoder around the ten digit classes of MNIST, fully unsupervised: no label ever enters training. Handed to a reinforcement-learning agent as an intrinsic reward, it supplies the exploration that task rewards lack, improving on the task baseline in nine of ten environments and collapsing in none. Complexity generation, abstraction, and exploration, ordinarily pursued with unrelated objectives in separate fields, thus emerge from ascent on one differentiable quantity, and the projections of intelligence gain a common quantitative footing.

Keywords Learnable Novelty · Epiplexity · Novelty Search · Minimum Description Length · Reservoir Computing · Neural Cellular Automata

## 1 Introduction

Few concepts are invoked across as many disciplines as intelligence, and few are theorized in as many incompatible ways. To statistics and machine learning it is extreme compression of data; to the study of complex systems it is the emergence of universal computation; in the interaction of an agent with its environment it is open-ended adaptive behavior. Each appearance has its own literature and its own objective function, and the literatures rarely meet. Here we show that these appearances follow from a single principle: the pursuit of learnable novelty.

Many creative processes unfold without a preset destination. Biological evolution has no fixed target, and scientific discovery often proceeds without knowing where it will lead. Both illustrate search in which the next direction cannot be specified in advance. Lehman and Stanley [2011] made this intuition operational as novelty search, which abandons objectives, rewards only behavior not seen before, and thereby escapes the deceptive local optima that trap goal directed search. A parallel tradition holds that compression is intelligence: a model that compresses a data stream better has captured more of the mechanism that generated it, and generalizes better for it [Hutter, 2005, Deletang´ et al., 2024]. In the same spirit, the free-energy principle [Friston, 2010] holds that a competent agent minimizes its cumulative surprise, keeping its world compressed. Once these ideas are turned into optimization objectives, however, they often fail, each in its own way. A learner that maximizes novelty is captured by a noisy television screen: unpredictable forever, hence forever novel, it teaches nothing [Pathak et al., 2017, Burda et al., 2019]. A learner that minimizes surprise retreats into a dark room where nothing happens at all, because nothing is easier to predict [Sun and Firestone, 2020]. The two pathologies are mirror images with a common cause: both objectives conflate the total novelty in the data with the structure a bounded mind can absorb.

![](images/9f06f3989df707d0881ac268d1696681c4925470d511e6d22b8270eee47f8a75.jpg)  
Figure 1: (a) An observer receives a stream one item at a time. It predicts each item before seeing it, is surprised by the difference, and updates itself, so as the stream’s regularities are absorbed the surprise falls, though never below the floor of irreducible noise. The learnable part of the accumulated surprise, in blue, is the epiplexity $\bar { S } ^ { \phi }$ . A noisy TV is all noise, and a dark room offers no surprise at all. (b) The same quantity serves as an objective. The observed system produces data, the bounded observer condenses them into the single number $S ^ { \phi } ,$ , and the gradient of that number flows back and reshapes the system. Driven by this alone, a cellular automaton develops solitons, an image encoder separates the digit classes, and an agent learns to explore. (c) Behind $S ^ { \phi }$ is the description length of what the observer has learned. Redundant directions merge and add nothing, and each remaining direction takes about as many bits as its magnitude has digits, so $S ^ { \phi }$ measures how much independent structure was learned rather than how large it is.

Consider instead a learner of finite compute observing data one item at a time. Each item carries a quantum of surprise and an occasion to update the learner’s model; as the stream accumulates, its regularities are internalized into the model while its irreducible randomness remains forever uncompressed. The surprise summed over the whole course is exactly the stream’s minimum description length under that compute bound [Dawid, 1984, Blier and Ollivier, 2018, Rissanen, 1978, Grunwald, 2007, Finzi et al., 2026]. The total splits in two: the program length of the best model¨ that finite compute can fit, and the residual that this model can never reduce (Figure 1a). The first part, the structure a bounded mind genuinely carries away from the data, is the epiplexity recently named by Finzi et al. [2026], and it is what we mean by learnable novelty; Section 2 states the decomposition formally. That work computes epiplexity as a measure of data already in hand; we read the same quantity as learnable novelty and give it a cheap, differentiable estimator, which turns it from a property to be measured into an objective a system can be driven to maximize. Seen through this decomposition, a noisy television is all residual, and a dark room contributes to neither part. Maximizing the learnable part alone therefore removes both pathologies at once.

What kind of system results when learnable novelty is maximized? For a bounded learner to keep extracting rich structure, the system it learns from must sit at the boundary of order and chaos: too ordered and there is nothing to learn, too chaotic and nothing is learnable. A dynamical system optimized for learnable novelty should therefore approach general-purpose computation, since only a system that can compute arbitrarily can keep producing learnable structure without bound [Wolfram, 1984, Langton, 1990, Cook, 2004]. A representation optimized for learnable novelty must shed redundancy and emit as many mutually distinguishable, recoverable responses as the data support, so categorylike structure should emerge without supervision. And an agent whose policy maximizes the learnable novelty of its own future is an agent whose death or stagnation terminates that extraction: it is driven to avoid termination, to preserve its capacity to act, and to keep its exchange with the environment rich. This sharpens the causal-entropic [Wissner-Gross and Freer, 2013] and empowerment [Klyubin et al., 2005, Salge et al., 2014] accounts of intelligent behavior: the reachable futures must be not merely diverse but learnable.

Testing these predictions means evaluating learnable novelty inside an optimization loop, and there its cost becomes prohibitive: the definition of epiplexity calls for a search over bounded-compute models, and the original work trains a neural network for every system scored [Finzi et al., 2026]. But the definition does not fix what the bounded learner is, only that it learns. A program class qualifies, a neural network qualifies, and so does a reservoir computer [Jaeger and Haas, 2004, Maass et al., 2002], in which all learnable capacity resides in a linear readout whose optimum is the closed-form solution of a ridge regression. With the reservoir as the learner, the score becomes cheap, deterministic, and differentiable in whatever produced the data: learnable novelty becomes not merely measurable but directly optimizable (Figure 1b).

Used as a measure, with no training of any kind, it reproduces complexity rankings accumulated over decades of study: across the elementary cellular automata it places the Turing-complete rule 110 [Cook, 2004] at the top. Used as an objective, its gradient drives structure into existence. With no supervisory signal, it carries a one-dimensional neural cellular automaton [Mordvintsev et al., 2020] from simple behavior into a system of complex solitons, coherent traveling structures that collide and interact. The same gradient carries a randomly initialized encoder of MNIST [LeCun et $\mathrm { a l . } .$ , 1998] into a representation in which the digit classes separate, with no label ever entering training. Used as a reinforcement-learning reward, it drives an agent to explore novel, richer behavior on its own, reaching higher return faster in sparse-reward, deceptive environments.

## 2 From Novelty to Epiplexity

Novelty search made the pursuit of the unseen operational but left novelty itself undefined: it hand-picks a behavior descriptor and rewards distance in that chosen space [Lehman and Stanley, 2011]. A measure of novelty should instead be intrinsic to the data, and the natural raw material is surprise. Consider transmitting a sequence $\boldsymbol { Y } = \left( y _ { 1 } , \dots , y _ { N } \right)$ to a receiver who already holds the corresponding inputs $\bar { X = ( \ v { x } _ { 1 } , \ v { x } _ { 1 } , \ v { x } _ { 2 } , \ v { x } _ { N } ) }$ . The data arrive one symbol at a time, and before each arrival the receiver predicts the symbol from what it has already seen, $p ( y _ { i } \mid y _ { < i } , X )$ . When y is revealed, the receiver pays a surprise cost $\ell _ { i } = - \log _ { 2 } { p ( y _ { i } \mid y _ { < i } } , X )$ and updates its predictor on the new datum. Summed over the sequence, the chain rule collapses the total cost to a single quantity,

$$
L = \sum _ { i = 1 } ^ { N } \ell _ { i } = - \log _ { 2 } \prod _ { i = 1 } ^ { N } p ( y _ { i } \mid y _ { < i } , X ) = - \log _ { 2 } p ( Y \mid X ) ,\tag{1}
$$

the prequential description length [Dawid, 1984, Blier and Ollivier, 2018]: the number of bits the receiver pays before X determines $Y$ . Cumulative surprise is a natural gauge of novelty: the more an observer who holds X is surprised in the course of observing $Y ,$ the more novel the relationship between them. Rewarding L in place of distance in a hand-chosen behavior space preserves the drive toward the unseen while removing the arbitrary descriptor.

Read this way, two established programs occupy the two extremes of one quantity. Novelty search maximizes L: high cumulative surprise marks behavior not seen before, and chasing it outperforms goal-directed search on deceptive problems [Lehman and Stanley, 2011]. The free-energy principle minimizes $L \colon$ low cumulative surprise marks an internal model that fits its inputs, and a surprise-minimizing agent is read as self-organizing [Friston, 2010]. Each fails, but for opposite reasons. A noisy television maximizes L per unit time because every frame is independent random noise, so a surprise-seeking agent parks in front of it and learns nothing [Pathak et al., 2017, Burda et al., 2019]. A dark room minimizes L because every input repeats the last, so a surprise-minimizing agent prefers it to any structured environment [Sun and Firestone, 2020]. The two failures share a root: L is a sum of two distinct components, the surprise that can be learned and the surprise that cannot. An objective that sees only the sum can be driven to either extreme by moving one component alone.

The minimum description length principle makes the two components precise [Rissanen, 1978, Grunwald, 2007, ¨ Solomonoff, 1964]. Among all models that could carry $Y$ to a receiver holding X, the minimizing one splits the transmission into a description of the model and the residual the model cannot account for,

$$
L \approx \underset { M \in \mathcal { M } } { \mathrm { m i n } } \Big [ | M | - \log _ { 2 } p ( Y \mid X , M ) \Big ] ,\tag{2}
$$

where the approximation errs only in lower-order terms [Grunwald, 2007]. The first term, the program length¨ $| M |$ is the part of the relationship an observer can learn and reuse on future inputs. The second is the part that, at the minimum, is unlearnable: not because no model could compress it further, but because any model that tried would only lengthen the total transmission. This decomposition identifies the flaw in each of the two earlier programs. Novelty search is dominated in the extreme by the residual term: the noisy television contributes nothing to $| M |$ . The free-energy principle, in minimizing prediction error, compresses |M | along with it, and is therefore drawn to the dark room. Both flaws point to the same conclusion: the quantity worth pursuing is |M| alone.

Equation equation 2 is uncomputable in general, since no search can visit every program in $\mathcal { M } ,$ , and real observers hold only finite compute; we therefore consider only a finite set of halting programs $\mathcal { M } _ { \phi }$ , given by a fixed bounded observer ϕ. The computable restriction of the MDL problem is

$$
\begin{array} { r l } & { L ^ { \phi } ( \boldsymbol { Y } \mid \boldsymbol { X } ) = \underset { M \in \mathcal { M } _ { \phi } } { \mathrm { m i n } } \Big [ \left| M \right| - \log _ { 2 } p ( \boldsymbol { Y } \mid \boldsymbol { X } , M ) \Big ] , } \\ & { M _ { \phi } ^ { * } ( \boldsymbol { Y } \mid \boldsymbol { X } ) = \arg \underset { M \in \mathcal { M } _ { \phi } } { \mathrm { m i n } } \Big [ \left| M \right| - \log _ { 2 } p ( \boldsymbol { Y } \mid \boldsymbol { X } , M ) \Big ] . } \end{array}\tag{3}
$$

Here we define $| M _ { \phi } ^ { * } |$ as the learnable novelty; it is precisely the epiplexity of Finzi et al. [2026], the structure a finite-compute learner can actually extract from the data:

$$
S ^ { \phi } ( Y \mid X ) \ : = \ : \vert M _ { \phi } ^ { * } ( Y \mid X ) \vert .\tag{4}
$$

By contrast, novelty search must postulate its behavior space by hand, whereas learnable novelty does not: it needs only a bounded observer to decide what counts as novel, and that boundedness is why both the noisy television and the dark room contribute zero to $| M _ { \phi } ^ { * } |$

Epiplexity measures data that are given; learnable novelty is that quantity pursued as a goal, and it asks that the process generating the data be optimized. When the optimized object is the dynamics of the data, maximizing $S ^ { \phi }$ pushes it into the regime that emits the most learnable structure: trivial dynamics offer nothing to learn and fully chaotic dynamics nothing learnable, so the maximum lies between order and chaos [Langton, 1990, Packard, 1988], where some systems can sustain universal computation [Wolfram, 1984, Cook, 2004]. When the optimized object is a representation $x \mapsto z$ of static data, maximization forces a bounded observer to recover from x as many independent, learnable distinctions in z as possible while shedding redundant information, and this is precisely compression: the code then organizes into clusters, the structure long associated with compression as understanding [Hutter, 2005, Deletang et al., 2024]. When´ the optimized object is the policy of an embodied agent, maximizing the learnable novelty of its reachable futures selects the actions that lead to rich future states; conversely, actions that terminate the agent or collapse its options remove reachable futures and lower the score, while actions that leave the environment in a richer state preserve them. This is the causal-entropic account of intelligent behavior [Wissner-Gross and Freer, 2013]; learnable novelty goes one step further and asks that the reachable futures be not merely diverse but learnable. Section 4 tests all three predictions.

## 3 A Closed-Form Estimator of Epiplexity

Evaluating epiplexity requires finding the optimum in the bounded model space $\mathcal { M } _ { \phi } .$ , which amounts to a full training run for every system scored; the original epiplexity work does exactly this [Finzi et al., 2026]. This is not only computationally expensive but also opaque to gradients: nothing backpropagates through such a training run to the system being scored, so epiplexity evaluated this way serves as a measure but not as an objective.

Yet the definition does not prescribe a particular learner architecture; it only requires a system with bounded learning capacity. A reservoir computer [Jaeger and Haas, 2004, Maass et al., 2002] fits this requirement exactly: a fixed, randomly initialized nonlinear feature map followed by a single linear readout layer. With the reservoir as the bounded learner, finding the optimal model reduces to solving a ridge regression in closed form, making epiplexity cheap to evaluate, deterministic, and fully differentiable.

Concretely, let ϕ be an untrained, fixed random nonlinear map. Applied to N inputs X, it yields a feature matrix $H =$ $\phi ( X ) \in \breve { \mathbb { R } } ^ { N \times m }$ , where m is the reservoir feature dimension, with targets $Y \in \overset { \mathbf { \cdot } } { \mathbb { R } } ^ { N \times D }$ (the construction of ϕ is given in Appendix A.3). All learnable capacity resides in the linear readout matrix $W \in \mathbb { R } ^ { m \times D }$ , so $\mathcal { M } _ { \phi }$ can be defined as ϕ followed by every possible linear readout. In other words, $W$ is a program defined on the reservoir $\phi ,$ , and computing the model’s program length reduces to computing the description length of the linear operator $W$

Under the minimum description length (MDL) framework [Rissanen, 1978, Grunwald, 2007], the optimal readout¨ minimizes the total description length: a residual part plus a weight part ${ \mathcal { C } } ( W , \phi )$ . Assuming Gaussian residual noise $\boldsymbol { Y } = \boldsymbol { H } \boldsymbol { W } + \boldsymbol { \epsilon }$ , the residual part in bits equals a scaled mean squared error, and the total description length is

$$
L ( W ) = { \frac { \| Y - H W \| _ { F } ^ { 2 } } { 2 \sigma ^ { 2 } \ln 2 } } + { \mathcal C } ( W , \phi ) .\tag{5}
$$

For the weight part we take a spectral description length based on the singular values $s _ { i } ( W )$ of the readout:

$$
\mathcal { C } _ { \mathrm { s p e c } } ( W ) = \alpha \log _ { 2 } \operatorname* { d e t } \bigl ( I _ { m } + \eta W W ^ { \top } \bigr ) = \alpha \sum _ { i } \log _ { 2 } \bigl ( 1 + \eta s _ { i } ( W ) ^ { 2 } \bigr ) ,\tag{6}
$$

where $\eta$ is a resolution parameter and α is an overall scale on the description length. Since α changes neither the ranking between systems nor the direction of the gradient, all experiments fix $\alpha = 1 / 2$ and set $\eta = 1$ , except the MNIST encoder, which uses $\eta = 3 0$ (Table 3). This log-determinant form follows the MDL principle that model complexity is measured by description length, matches the coding-rate objectives used in representation learning [Rissanen, 1978, Grunwald, 2007, Yu et al., 2020], and can also be derived from a hierarchical Gaussian prior (Appendix C). Its¨ information-theoretic advantage is that scaling adds only logarithmic cost, and when readout directions coincide or are highly redundant they contribute no new independent singular value and incur only a logarithmically small additional cost, in compliance with the compression principle of algorithmic information theory (Figure 1c).

With equation 6 as the weight part, however, the total description length equation 5 has no closed-form minimizer: solving it requires an inner iterative optimization, which raises the cost of every evaluation and obstructs the gradients we want to pass through $W$ to the system being scored. We therefore approximate the minimization by a ridge regression [Tikhonov and Arsenin, 1977]; pricing weights by an $L _ { 2 }$ penalty on MDL grounds is a classical move in machine learning [Hinton and van Camp, 1993], and a recent result relates the minimum weight norm of a fixedprecision network to the Kolmogorov complexity of the string it generates [Musat, 2026]. A Taylor expansion shows the two are close: for small $\begin{array} { r } { W { \ ' { , } \log _ { 2 } \operatorname* { d e t } \dot { ( I _ { m } + \eta W W ^ { \top } ) } } \approx \eta \| W \| _ { F } ^ { 2 } / \ln 2 } \end{array}$ , so the spectral description length itself reduces to the quadratic penalty of the ridge, and the residual scale $\sigma ^ { 2 }$ merges with $\alpha$ and $\eta$ into a single ridge parameter $\lambda ;$ the ridge’s own shrinkage in turn keeps the readout in the small-norm regime where the expansion is accurate. To keep the features on a consistent scale, we standardize each feature column before solving the ridge problem; the target is centered and divided by a fixed scale factor $u _ { Y }$ posited in advance:

$$
\tilde { H } _ { \cdot c } = \frac { H _ { \cdot c } - \mu _ { c } } { \hat { \sigma } _ { c } \sqrt { m } } , \qquad \tilde { Y } = \frac { Y - \mu _ { Y } } { u _ { Y } } ,\tag{7}
$$

where $\mu _ { c }$ and $\hat { \sigma } _ { c }$ are the empirical mean and standard deviation of feature column $c ,$ while $\mu _ { Y }$ and $u _ { Y }$ are the target centering and scale constants used by the estimator instance. The target is divided by $u _ { Y }$ rather than by its own empirical standard deviation because the target’s magnitude itself carries information: a larger-magnitude target demands a larger readout, which the spectral description length equation 6 prices at more bits, logarithmically in its scale; $u _ { Y }$ thus acts as the measurement precision posited for the target, the unit relative to which readout magnitude and residual are priced. The $\sqrt { m }$ factor keeps the output scale of a random readout with i.i.d. standard normal entries invariant across feature widths

The optimal readout can then be written in closed form:

$$
W _ { \lambda } = \arg \operatorname* { m i n } _ { W } \| \tilde { Y } - \tilde { H } W \| _ { F } ^ { 2 } + \lambda \| W \| _ { F } ^ { 2 } = ( \tilde { H } ^ { \top } \tilde { H } + \lambda I _ { m } ) ^ { - 1 } \tilde { H } ^ { \top } \tilde { Y } .\tag{8}
$$

Substituting $W _ { \lambda }$ into the spectral description length gives the complete reservoir-based closed-form estimator of epiplexity:

$$
\begin{array} { l } { { S ^ { \phi } ( Y \mid X ) = \displaystyle \frac { 1 } { 2 } \log _ { 2 } \operatorname* { d e t } \bigl ( I _ { m } + \eta W _ { \lambda } W _ { \lambda } ^ { \top } \bigr ) } } \\ { { \mathrm { ~ } = \displaystyle \frac { 1 } { 2 } \sum _ { i } \log _ { 2 } \bigl ( 1 + \eta s _ { i } ( W _ { \lambda } ) ^ { 2 } \bigr ) , } } \\ { { \mathrm { ~ } \mathrm { ~ w h e r e ~ } W _ { \lambda } = ( \tilde { H } ^ { \top } \tilde { H } + \lambda I _ { m } ) ^ { - 1 } \tilde { H } ^ { \top } \tilde { Y } . } } \end{array}\tag{9}
$$

Through this construction, an expensive bounded-model search is compressed into a closed-form ridge solve. The optimum is unique, and $S ^ { \phi }$ is differentiable in $( X , Y )$ . In practice, for reasons of numerical stability, we never solve the normal equations of equation 8 directly; an algebraically equivalent, better-conditioned least-squares solve computes the same $W _ { \lambda }$ and remains differentiable (Appendix E). Appendix D also minimizes the total description length equation 5 directly, without the approximation: the exact solution extracts more bits from the same data but ranks systems almost identically to the ridge readout.

## 4 Experiments

Intelligent behavior often appears in different guises in different systems, and we propose that these are all the product of maximizing learnable novelty. We therefore test, in turn, nonlinear dynamical systems, representation learning, and reinforcement-learning tasks. Architectures, sampling procedures, and optimization settings for all experiments are included in Appendix A.

![](images/6084e21c2aef0f40bf0495f56fedf7feef8465822ea8c474692511476265b470.jpg)  
Figure 2: $S ^ { \phi }$ over all 88 locally unique elementary cellular automata (top fourteen shown, together with the reference rules). Bars are colored by Wolfram class [Wolfram, 2002]: II periodic, III chaotic, IV complex (legend); insets show the space-time diagrams (time downward) of the six reference rules 1, 2, 3, 30, 54, and 110. Each bar is the mean over ten independent draws of the random reservoir and the input ensemble, and error bars show one standard deviation. Rule 110 (Turing-complete, class IV) is the clear maximum over the whole space; at the other end, the rules whose sampled attractor dynamics are constant score exactly zero (none appears in the figure), and the near-trivial periodic rules 1 and 2 are the lowest-scoring rules shown.

## 4.1 Dynamical systems

Elementary cellular automata (ECA) are among the simplest nonlinear dynamical systems: a one-dimensional binary lattice in which each site determines its next state from its own state and those of its nearest neighbors. Each ECA rule takes only 8 bits to describe, yet within these minimal rules lies the potential for emergent complex computation. Different ECA rules produce a rich range of behaviors (simple, chaotic, and complex), and among Wolfram’s elementary rules, rule 110 is the only one currently proven Turing-complete [Cook, 2004]. ECA are therefore the ideal testbed for asking what kind of dynamics maximizes learnable novelty.

For the discrete, finite-space elementary cellular automata we perform an exhaustive evaluation. After removing the various symmetries, we select 88 independent rules; for each we sample stationary states as the initial condition $\bar { X }$ on a width-64 ring and stack the next 32 one-step evolutions into the target Y , scoring the map with equation 9 through a convolutional reservoir. Rule 110 ranks highest in the entire rule space, the lowest scores, exactly zero, go to the rules whose sampled attractor dynamics are constant, the near-trivial periodic rules 1 and 2 score low, and the chaotic rule 30 lies in between, below the complex rule 54 (Figure 2). As a pure measurement tool, the closed-form estimator reproduces the classical complexity classification without any supervision, and rule 110’s top rank is robust to the estimator’s hyperparameters (Appendix B). The same method, with the reservoir matched to the data geometry, also reproduces the complexity ordering of continuous-time dynamical systems (Appendix F), confirming the estimator’s validity as a measure.

To further test what happens when this learnable novelty is directly optimized, we turn to the continuous, two-channel neural cellular automata (NCA) [Mordvintsev et al., 2020]. The local update $G _ { \theta }$ applies a learnable convolutional map $g _ { \theta }$ and renormalizes each site; we test it in two forms, a direct update

$$
x _ { t + 1 } = G _ { \theta } ( x _ { t } ) = { \mathrm { n o r m a l i z e } } \left[ g _ { \theta } ( x _ { t } ) \right] ,\tag{10}
$$

and a residual update G (x ) = normalize $\left\lceil x _ { t } + g _ { \theta } ( x _ { t } ) \right\rceil$ that adds a skip connection around $_ { g _ { \boldsymbol { \theta } } ; }$ here normalize fixes the two-channel vector at each site to unit length. Because $G _ { \theta }$ is differentiable, learnable novelty can be maximized by gradient ascent on θ directly. At each training step, a batch of initial states is sampled and run forward for 32 gradient-free burn-in steps to reach a steady state, yielding $X \colon$ ; the dynamics are then rolled out differentially and the

a  
Training step  
![](images/5350a9c2f0c82a791057c1f73a2be0588c04e8c88265975ebc0b49d9c902a459.jpg)

![](images/b872d3d85a672abce895bf2d6c51eec8d6840411adc00b57b6fde80c0934ac03.jpg)

![](images/8b925a2d0880688eb733130f3a3430f6c37354bea191feabadda008526418cc7.jpg)  
Figure 3: Inverse design of a one-dimensional NCA by gradient ascent on a single epiplexity scalar. (a) Space–time diagrams of the learned rule (time downward) for three random seeds: one row per seed, one column per training step from 0 to 2000. Every seed develops complex solitons from a simple initial rule: localized structures that travel at fixed velocity and interact on collision. (b) $S ^ { \phi }$ over training for each of the three seeds individually. (c) $S ^ { \phi }$ for both update rules, each drawn as the mean (line) ± one standard deviation (shaded band) over nine independent seeds.

target stacks the next τ states,

$$
Y _ { \theta } ( X , \tau ) = \bigl ( G _ { \theta } ( X ) , G _ { \theta } ^ { 2 } ( X ) , \ldots , G _ { \theta } ^ { \tau } ( X ) \bigr ) .\tag{11}
$$

Figure 3 uses $\tau = 8 ,$ scored by the frozen reservoir estimator, and the objective is simply

$$
\operatorname* { m a x } _ { \theta } \ S ^ { \phi } ( Y _ { \theta } ( X , \tau ) \mid X ) .\tag{12}
$$

As the score rises, the initially simple rule spontaneously develops solitons: localized coherent structures that travel at fixed velocity and interact on collision (Figure 3a; Appendix G). Solitons are often a hallmark of a system’s capacity for information transmission and combination: rule 110 uses them to carry and combine information. The regime is insensitive to the exact form of the local update: the direct and residual normalized updates climb to the same epiplexity band over nine seeds (Figure 3c) and both develop solitons at every seed (Figure 6). That gradient ascent reliably finds this regime is no accident: universal computation is where learnable novelty is unbounded (a system that can compute arbitrarily keeps producing structure a learner has not yet absorbed), so climbing learnable novelty naturally pushes the dynamics toward the edge of order and chaos, where coherent structures such as solitons live. Solitons suit the bounded observer particularly well: a structure propagating at fixed velocity transforms predictably from step to step, a regularity the linear readout captures cheaply, while its collisions keep producing configurations the readout has not yet absorbed.

![](images/3257aacf8846ddc885e28639b02fd49141cb7f13c2f29e77811a3f4b503e1130.jpg)

![](images/968b99b7e049d48ce1f95fe130b46f214a99982e0ff67e7f9537268aab5b3c29.jpg)  
Figure 4: Unsupervised MNIST encoder trained solely to maximize reservoir epiplexity. (a) Two-dimensional t-SNE projections of the representation at six training checkpoints; colors indicate the held-out digit label, used for visualization only. (b) The $S ^ { \phi }$ training curve, with dashed connectors marking the checkpoint each projection is taken from. (c) Accuracy with which a linear probe and a 5-nearest-neighbor classifier recover the digit from the code at the same six checkpoints (chance 0.1, dotted); both rise with the epiplexity, the linear probe from 0.53 to 0.89 and the 5-nearest-neighbor from 0.66 to 0.89. Compact per-digit regions emerge progressively as the epiplexity rises, even though no class label ever enters training.

## 4.2 Representation learning

If the object being optimized is a representation map, maximizing its learnable novelty should force the encoder to shed redundancy and spontaneously organize around the latent categories of the data. We test this hypothesis on MNIST [LeCun et al., 1998]. A trainable encoder $E _ { \theta }$ maps an image $x \in X$ to a 64-dimensional feature vector $z =$ $E _ { \theta } ( x ) \in \mathbb { R } ^ { D }$ , normalized to unit length, and is trained to maximize the learnable novelty of its own code against a fixed random MLP reservoir (Appendix G); no class label enters at any stage.

Here we maximize $S ^ { \phi } ( Z = E _ { \theta } ( X ) \mid X )$ . After training with no class labels whatsoever, two-dimensional t-SNE projections [van der Maaten and Hinton, 2008] of the code at successive checkpoints show the initially entangled distribution progressively converging into clusters largely separated by digit class (Figure 4). A linear probe [Alain and Bengio, 2016] and a 5-nearest-neighbor classifier confirm this quantitatively: the accuracy with which each recovers the digit from the code rises together with the epiplexity, reaching 0.89 for both probes by the end of training (Figure 4c). The resulting representation quality is stable to moderate one-at-a-time changes of the training and estimator settings (Appendix G).

Under this objective, if the encoder merely represents highly redundant information in the data, such as the black background shared by all MNIST samples, this information barely varies across samples and contributes nothing new from the standpoint of learnable novelty. To maximize the score, the encoder must capture the features that create substantive differences between inputs. Maximizing learnable novelty is therefore implicit data compression: it forces the encoder to shed redundancy and retain only the most discriminative factors of the data. On MNIST, the dominant such factor is the digit itself. The categorical structure of the representation space emerges spontaneously in the pursuit of this single metric.

This spontaneous cluster structure can also be read through the information bottleneck [Tishby et al., 1999]. For an input X, a relevance variable $Y .$ , and an intermediate representation $Z ,$ the bottleneck minimizes $I ( X ; Z ) - \bar { \beta } I ( Y ; Z )$ over encoding distributions: it keeps the information in Z that bears on Y and compresses the rest. The bottleneck needs the external variable Y to decide which bits are worth keeping; in our objective that criterion is supplied implicitly by the decodability of the bounded observer: whatever structure the reservoir’s short readout can recover counts as relevant. Ridge shrinkage biases this criterion toward functions of low norm in the random-feature kernel space, functions that vary smoothly along the data manifold, and among these the class is the factor carrying the most discriminative information (the cluster assumption of semi-supervised learning [Chapelle et al., 2006]); this experiment sets $\lambda = 3 ,$ far above the other experiments (Table 3), precisely so that the relevance criterion admits only this smooth structure. The role of the compression term $I ( X ; Z )$ falls to the structural bottleneck: the code dimension is finite, and the spectral description length is nearly insensitive to repeated readout directions, so redundancy is squeezed out of the code.

Table 1: Epiplexity as a reinforcement-learning reward across ten tasks, mean ± standard deviation over ten seeds at 600,000 steps. Columns: the return under the task reward alone; the trajectory’s epiplexity alone (the agent never sees the task); the task reward plus a state-magnitude bonus $( \left. o _ { t } \right. ^ { 2 }$ , the squared norm of the input-normalized state); and the task reward plus the epiplexity bonus. Bold marks a run that improves on the task-reward baseline: the epiplexity bonus does so on every task but Walker2d and collapses on none (on Walker2d, epiplexity alone in fact exceeds the task reward), whereas the magnitude control falls below the baseline on Hopper, Walker2d, and LunarLander.
<table><tr><td>Task</td><td></td><td></td><td>Task reward Epiplexity only Task + magnitude Task + epiplexity</td><td></td></tr><tr><td colspan="5">Sparse / deceptive classic control</td></tr><tr><td>Acrobot</td><td> $- 1 6 7 \pm 1 6 6$ </td><td> $- 5 0 0 \pm 0$ </td><td> $- 8 9 \pm 4$ </td><td> $- 8 3 \pm 2$ </td></tr><tr><td>MountainCarContinuous</td><td> $2 8 \pm 4 3$ </td><td> $- 9 7 \pm 4$ </td><td> ${ \bf 9 3 \pm 1 }$ </td><td> ${ \bf 9 3 \pm 1 }$ </td></tr><tr><td colspan="5">MuJoCo / Box2D locomotion</td></tr><tr><td>Hopper</td><td> $1 8 7 9 \pm 3 2 5$ </td><td> $1 0 0 6 \pm 2 1$ </td><td> $5 1 6 \pm 1 2 8$ </td><td> $\mathbf { 2 1 9 2 } \pm \mathbf { 2 7 0 }$ </td></tr><tr><td>BipedalWalker</td><td> $1 2 5 \pm 7 4$ </td><td> $- 5 9 \pm 4 2$ </td><td> ${ \bf 1 4 6 \pm 5 1 }$ </td><td> ${ \bf 1 5 1 } \pm { \bf 4 9 }$ </td></tr><tr><td>HalfCheetah</td><td> $3 6 2 \pm 2 0 1$ </td><td> $- 1 8 1 \pm 2 4 4$ </td><td> ${ \bf 6 2 3 \pm 2 1 2 }$ </td><td> ${ \bf 3 9 3 \pm 2 6 0 }$ </td></tr><tr><td>Walker2d</td><td> $2 9 6 \pm 4 5$ </td><td> ${ \bf 3 2 7 \pm 4 5 }$ </td><td> $2 9 4 \pm 3 2$ </td><td> $2 8 5 \pm 4 1$ </td></tr><tr><td>Swimmer</td><td> $1 8 1 \pm 7 6$ </td><td> $- 1 2 \pm 2 6$ </td><td> ${ \bf 1 9 4 } \pm { \bf 7 6 }$ </td><td> ${ \bf 2 0 6 } \pm { \bf 8 6 }$ </td></tr><tr><td colspan="5">Sparse navigation</td></tr><tr><td>PointMaze</td><td> $2 2 9 \pm 7 7$ </td><td> $6 \pm 3$ </td><td> ${ \bf 2 4 2 \pm 7 9 }$ </td><td> ${ \bf 2 5 6 \pm 2 2 }$ </td></tr><tr><td colspan="5">Dense-reward control</td></tr><tr><td>LunarLander</td><td> $1 6 9 \pm 7 4$ </td><td> $- 4 3 8 \pm 3 9 3$ </td><td> $- 1 7 1 \pm 3 5$ </td><td> ${ \bf 2 0 8 \pm 2 5 }$ </td></tr><tr><td>Pendulum</td><td> $- 1 0 4 4 \pm 4 2$ </td><td> $- 1 0 9 2 \pm 5 6$ </td><td> $\mathbf { - 1 0 1 6 \pm 2 1 }$ </td><td> ${ \bf - 9 8 7 \pm 2 3 }$ </td></tr></table>

## 4.3 Reinforcement learning

For an agent situated in an environment, pursuing learnable novelty should steer it away from dead ends and sustain the richness of its behavior. The drive is a relative of empowerment [Klyubin et al., 2005, Salge et al., 2014], which maximizes the channel capacity from actions to future states and so rewards control over the future; learnable novelty asks in addition that those futures be learnable by the bounded observer. Because gradients cannot propagate through the environment, we hand the same closed-form score to a standard PPO algorithm [Schulman et al., 2017, Raffin et al., 2021] as an intrinsic reward, and compare four conditions on each task: the environment’s task reward alone, the trajectory’s epiplexity alone (the agent never sees the task), the task reward plus a small epiplexity bonus, and a state-magnitude control introduced below.

From the observation trajectory $o _ { 0 } , o _ { 1 } , \ldots ,$ at each step the map from $\begin{array} { r l r } { x } & { { } = } & { o _ { t } } \end{array}$ to the future window $y =$ $( o _ { t + 1 } , \ldots , o _ { t + \tau } )$ is scored jointly by a frozen reservoir estimator of the same construction. To keep the reward on coherent novelty rather than noise or simple behavior, we adopt two fixed settings: the reservoir is kept small, so it fits a structured trajectory but not a chaotic one and the reward favors regular motion; and the window horizon τ is matched to the characteristic time over which the state changes appreciably. To make the reward dense, we define the per-step bonus as the increment the latest state adds to the trajectory’s epiplexity, so that in the mixed condition the agent maximizes $r _ { t } = r _ { t } ^ { \mathrm { t a s k } } + \beta \left( S _ { t } ^ { \phi } - S _ { t - 1 } ^ { \phi } \right)$ , with the weight $\beta$ calibrated per environment (Appendix H); where the task reward is flat, the increment supplies the gradient that drives the agent to explore new behavior.

Across ten environments spanning classic control, MuJoCo locomotion, and maze navigation, the epiplexity bonus improves on the task reward on nine tasks (Table 1). On the sparse and deceptive-reward tasks (Acrobot and MountainCarContinuous), the task reward alone yields returns that vary widely across seeds, with some seeds failing to converge; with the epiplexity bonus, all seeds solve the task and the across-seed standard deviation drops sharply. It supplies the exploration drive the task reward lacks (driving the cart back and forth to build momentum, pumping the acrobot up to its bar), turning unreliable exploration into reliable solving. On the higher-dimensional locomotion tasks the bonus also lifts the return, most on Hopper. On sparse maze navigation (PointMaze) the bonus likewise raises the return and sharply cuts its across-seed variance, from 77 to 22.

To verify that the agent is not merely cheating by chasing large state values (accumulating extreme coordinates in the physics engine), we introduce state magnitude as a control reward: the squared norm of the input-normalized state, calibrated identically (Table 1, magnitude column). When reaching large state coincides with the task (a walker’s forward position and velocity are themselves the large variables the task pays for), this crude bonus also improves on the baseline, on HalfCheetah by more than the epiplexity bonus does. But it is unstable: on Hopper, where large state means an extreme posture the agent cannot hold, the magnitude bonus drops far below the task reward, driving the agent to fall; on LunarLander it drops harder still, from a return of +169 to −171. The epiplexity bonus never collapses: across all ten tasks it stays at or above the task reward except on Walker2d, where it falls 4% short, while the magnitude control drops below the baseline on three tasks and far below on two. What sets learnable novelty apart is not a higher ceiling on any one task but its stability: it rewards state the bounded observer can compress, never the raw magnitude that aids one environment and ruins another.

The epiplexity-only column shows what learnable novelty alone can do. An agent rewarded only for its trajectory’s epiplexity never sees the task, and on most of these tasks it does not perform it: optimizing learnable novelty is not optimizing the goal, and on Acrobot reaching the goal would end the episode and cut off the agent’s own learnable novelty, so the epiplexity-only agent learns to avoid it. Learnable novelty alone is therefore not a task solver; its role is as a bonus: it supplies the exploration the task reward lacks while the task reward supplies the goal. The exceptions are Hopper and Walker2d, where moving forward is itself the richest trajectory: the epiplexity-only agent learns to locomote on its own, and on Walker2d it even exceeds the task reward itself (Table 1). The bonus does not help everywhere: on tasks where the task reward already affords adequate exploration, the learnable-novelty drive is a mild distraction (Walker2d, Table 1). But it helps exactly where exploration is the bottleneck, which is where an intrinsic drive is supposed to.

The prior work most directly related to these experiments is prediction-error curiosity [Pathak et al., 2017, Burda et al., 2019]: it likewise points the reward at states an internal predictor has not yet learned, but that reward must be read off a model trained alongside the exploration. The reservoir estimator removes this inner training loop: the bounded observer is fixed, and what it can learn is computed in closed form. Prediction-error exploration can also be trapped by environmental noise, whereas the learnable-novelty reward inherits epiplexity’s immunity to the noisy-television problem (Section 2): a region of pure noise inflates the agent’s per-step surprise yet adds nothing to the learnable novelty, so the reward is not drawn to noise. What it rewards is movement into state the bounded observer can still compress, not state it merely cannot predict.

## 5 Discussion

Complexity generation, abstraction, and exploration are ordinarily studied in separate fields and driven by objectives that owe nothing to one another. In the experiments reported here, all three were produced by a single quantity evaluated by a fixed observer of a single construction. Read as a measure, it recovered the classical complexity ordering of the elementary cellular automata without supervision, placing the one rule proven Turing-complete at the top of the space. Ascended as an objective, its gradient carried a neural cellular automaton from simple dynamics into a regime of complex solitons and organized the representation of an image encoder around the digit classes of MNIST, although no label ever entered training. Handed to an agent as an intrinsic reward, it supplied the exploration that task rewards lack, improving on the task reward in nine of ten environments and collapsing in none. The three phenomena, these results suggest, were never independent: they are projections of one quantity, learnable novelty, onto dynamics, representations, and behavior.

What separates this account from earlier theories of intelligence is that it places the observer at its center, inside the definition itself. All three experiments position a bounded observer of the same construction at the center of dynamical evolution, representation learning, and policy execution, and the quantity being maximized is defined relative to it. The intrinsic complexity of an automaton, the quality of a code, and the adaptivity of a policy thereby cease to be absolute properties of a system and become properties of a relationship: how much structure this particular bounded observer can extract from that system. The centrality of the observer has important precedents. Dennett’s intentional stance treats belief and agency as attributes an interpreter ascribes rather than intrinsic facts [Dennett, 1987]; Pattee’s epistemic cut locates the division between observer and observed within any act of measurement [Pattee, 2001]; and the same commitment runs through second-order cybernetics and relational biology [von Foerster, 1981, Rosen, 1991]. These traditions place the observer within the account of what can be said about a system. We carry this observercentered view into a theory of intelligence, treating complexity generation, abstraction, and adaptive behavior as expressions of the relation between a system and a bounded learner. More recently, Finzi et al. [2026] formalize the structure available to a computationally bounded observer as epiplexity, the length of the program it distills from data. We read the same quantity as novelty: under prequential coding [Dawid, 1984], the cumulative surprise of a learning observer splits into a learnable part and an unlearnable residual, and the two classical drives fail on opposite sides of this split: novelty search maximizes the sum and is dragged toward the residual, while the free-energy principle minimizes the sum and discards structure along with noise. Learnable novelty is the part both objectives needed and neither isolates.

Information theory has always contained an observer, but a silent one. Shannon’s receiver has unbounded compute and therefore no character of its own; the observer presupposed by Kolmogorov complexity is likewise free of resource limits. Predictive information [Bialek et al., 2001], the mutual information between the past of a stream and its future, comes closest to separating structure from randomness, yet still for that ideal observer: it counts whatever is predictable in principle, whether or not a bounded learner could extract it. Computational mechanics sharpens this into a construction, measuring extractable structure as the statistical complexity of the minimal set of causal states an observer needs to predict a process [Crutchfield and Young, 1989]; but that observer, too, is idealized, charged nothing for the compute its reconstruction demands. Resource-bounded refinements gave the observer a budget, yet it remained a static parameter in the definition of a measure: something a quantity is stated relative to, not an agent in its own right. Our experiments argue for a more active role, and we propose an operational definition to match: the observer is a learner, a system that receives sequential data, pays the cost of its surprise, and updates its predictor with every payment. This view also agrees with the premise of AIXI [Hutter, 2005], where all of an agent’s intelligence derives from the quality of the Solomonoff predictor [Solomonoff, 1964], an idealized sequential learner: the capacity to learn sets the ceiling on the capacity to behave intelligently.

The closest predecessor of the present objective is Schmidhuber’s compression progress [Schmidhuber, 2010, 2009]. The two share their premise (learning is compression), but their optima part company. Compression progress rewards the rate at which the description of experience shrinks, and the total shrinkage available is set by how far that description stands above its Kolmogorov complexity. An utterly bland, unchanging stretch of experience has minimal Kolmogorov complexity and therefore the largest room to shrink, so in the long run a maximizer of cumulative progress profits most from trajectories that compress well because they contain little: this rebuilds the dark-room problem [Sun and Firestone, 2020]. Learnable novelty closes this route by construction: the program a bounded observer extracts from a dark room has length near zero, and no amount of further observation makes it grow.

Two limitations bound these results and point to a direction for future work. The first is that our observer never grows. Freezing the reservoir at initialization is what buys the closed form, but it also fixes the boundary of the learnable once and for all: structure beyond the reservoir’s compressive reach is invisible to the score, and once an optimized system exhausts what its observer can read, learnable novelty saturates. In its present form the estimator captures only the shallow structure that is linearly readable from random features. The natural way past this is to let the observer into the optimization. When observer and observed co-evolve, the system is pushed to produce whatever structure its observer can currently absorb while the observer extends its reach in step, and the boundary of the learnable moves rather than the score saturating against it. Open-ended growth, on this account, asks for exactly that moving boundary. Large language models may be a ready substrate for this symmetric arrangement: through in-context learning a model behaves as a compute-bounded sequential learner, and as a generator of sequences it is at the same time the system being observed.

The second limitation concerns what learnable novelty is to the agent that pursues it. In our reinforcement-learning experiments it enters as a bonus: it reliably relieves the exploration bottleneck, but the direction of optimization is still anchored by a task reward imposed from outside. One extension would invert the relationship, converting the task reward into a modulation of where novelty is to be found, so that the agent’s underlying drive remains the pursuit of learnable novelty and the environment serves only to shape the landscape through which that pursuit moves. The environments tested here are also, almost without exception, finite games, in which the surest way to keep novelty flowing is to avoid terminal states; an agent rewarded for learnable novelty alone accordingly learns to survive, and sometimes to defer the very goal that would end the episode. Many of the settings that matter most are infinite games with no terminal state to guard against, and there the condition this framework adds to the causal-entropic account of intelligent behavior [Wissner-Gross and Freer, 2013] should carry more of the weight.

Compression, computation, and exploration need not be assigned separate, mutually isolated objectives: on three very different substrates, each emerged from the sustained pursuit of learnable novelty by a bounded observer. Taking the bounded learner as the primitive, restating existing theories from its standpoint, and letting observer and observed grow together are, we believe, key questions for future exploration.

## References

Guillaume Alain and Yoshua Bengio. Understanding intermediate layers using linear classifier probes. arXiv preprint arXiv:1610.01644, 2016.

William Bialek, Ilya Nemenman, and Naftali Tishby. Predictability, complexity, and learning. Neural Computation, 13(11):2409–2463, 2001.

Leonard Blier and Yann Ollivier. The description length of deep learning models. In ´ Advances in Neural Information Processing Systems, 2018.

Yuri Burda, Harrison Edwards, Amos Storkey, and Oleg Klimov. Exploration by random network distillation. In International Conference on Learning Representations, 2019.

Olivier Chapelle, Bernhard Scholkopf, and Alexander Zien, editors. ¨ Semi-Supervised Learning. MIT Press, 2006.

Matthew Cook. Universality in elementary cellular automata. Complex Systems, 15(1):1–40, 2004.

James P. Crutchfield and Karl Young. Inferring statistical complexity. Physical Review Letters, 63(2):105–108, 1989.

A. Philip Dawid. Present position and potential developments: Some personal views. statistical theory: The prequentia approach. Journal of the Royal Statistical Society, Series A, 147(2):278–292, 1984.

Gregoire Del´ etang, Anian Ruoss, Paul-Ambroise Duquenne, Elliot Catt, Tim Genewein, Christopher Mattern, Jordi´ Grau-Moya, Li Kevin Wenliang, Matthew Aitchison, Laurent Orseau, Marcus Hutter, and Joel Veness. Language modeling is compression. In International Conference on Learning Representations, 2024.

Daniel C. Dennett. The Intentional Stance. MIT Press, Cambridge, MA, 1987.

Marc Finzi, Shikai Qiu, Yiding Jiang, Pavel Izmailov, J. Zico Kolter, and Andrew Gordon Wilson. From entropy to epiplexity: Rethinking information for computationally bounded intelligence. arXiv preprint arXiv:2601.03220, 2026.

Karl Friston. The free-energy principle: A unified brain theory? Nature Reviews Neuroscience, 11(2):127–138, 2010.

Peter D. Grunwald.¨ The Minimum Description Length Principle. MIT Press, 2007.

Geoffrey E. Hinton and Drew van Camp. Keeping the neural networks simple by minimizing the description length of the weights. In Proceedings of the Sixth Annual Conference on Computational Learning Theory, pages 5–13, 1993.

Marcus Hutter. Universal Artificial Intelligence: Sequential Decisions Based on Algorithmic Probability. Springer, 2005.

Herbert Jaeger and Harald Haas. Harnessing nonlinearity: Predicting chaotic systems and saving energy in wireless communication. Science, 304(5667):78–80, 2004.

Alexander S. Klyubin, Daniel Polani, and Chrystopher L. Nehaniv. Empowerment: A universal agent-centric measure of control. In Proceedings of the IEEE Congress on Evolutionary Computation, 2005.

Christopher G. Langton. Computation at the edge of chaos: Phase transitions and emergent computation. Physica D: Nonlinear Phenomena, 42(1-3):12–37, 1990.

Yann LeCun, Leon Bottou, Yoshua Bengio, and Patrick Haffner. Gradient-based learning applied to document recog-´ nition. Proceedings of the IEEE, 86(11):2278–2324, 1998.

Joel Lehman and Kenneth O. Stanley. Abandoning objectives: Evolution through the search for novelty alone. Evolu tionary Computation, 19(2):189–223, 2011.

Wolfgang Maass, Thomas Natschlager, and Henry Markram. Real-time computing without stable states: A new¨ framework for neural computation based on perturbations. Neural Computation, 14(11):2531–2560, 2002.

Alexander Mordvintsev, Ettore Randazzo, Eyvind Niklasson, and Michael Levin. Growing neural cellular automata. Distill, 2020. doi: 10.23915/distill.00023.

Tiberiu Musat. Neural weight norm = Kolmogorov complexity. arXiv preprint arXiv:2605.10878, 2026.

Norman H. Packard. Adaptation toward the edge of chaos. In Dynamic Patterns in Complex Systems, pages 293–301. World Scientific, 1988.

Deepak Pathak, Pulkit Agrawal, Alexei A. Efros, and Trevor Darrell. Curiosity-driven exploration by self-supervised prediction. In International Conference on Machine Learning, pages 2778–2787, 2017.

Howard H. Pattee. The physics of symbols: bridging the epistemic cut. BioSystems, 60(1–3):5–21, 2001.

Ben Poole, Subhaneil Lahiri, Maithra Raghu, Jascha Sohl-Dickstein, and Surya Ganguli. Exponential expressivity in deep neural networks through transient chaos. In Advances in Neural Information Processing Systems, volume 29, 2016.

Antonin Raffin, Ashley Hill, Adam Gleave, Anssi Kanervisto, Maximilian Ernestus, and Noah Dormann. Stablebaselines3: Reliable reinforcement learning implementations. Journal of Machine Learning Research, 22(268): 1–8, 2021.

Jorma Rissanen. Modeling by shortest data description. Automatica, 14(5):465–471, 1978.

Robert Rosen. Life Itself: A Comprehensive Inquiry into the Nature, Origin, and Fabrication of Life. Columbia University Press, New York, 1991.

Christoph Salge, Cornelius Glackin, and Daniel Polani. Empowerment: An introduction. In Guided Self-Organization: Inception, pages 67–114. Springer, 2014.

Jurgen Schmidhuber. Ultimate cognition ¨ a la G \` odel. ¨ Cognitive Computation, 1(2):177–193, 2009.

Jurgen Schmidhuber. Formal theory of creativity, fun, and intrinsic motivation (1990–2010). ¨ IEEE Transactions on Autonomous Mental Development, 2(3):230–247, 2010.

Samuel S Schoenholz, Justin Gilmer, Surya Ganguli, and Jascha Sohl-Dickstein. Deep information propagation. In International Conference on Learning Representations, 2017.

John Schulman, Filip Wolski, Prafulla Dhariwal, Alec Radford, and Oleg Klimov. Proximal policy optimization algorithms. arXiv preprint arXiv:1707.06347, 2017.

Ray J. Solomonoff. A formal theory of inductive inference. part i. Information and Control, 7(1):1–22, 1964.

Zekun Sun and Chaz Firestone. The dark room problem. Trends in Cognitive Sciences, 24(5):346–348, 2020. doi: 10.1016/j.tics.2020.02.006.

A. N. Tikhonov and V. Y. Arsenin. Solutions of Ill-Posed Problems. Winston, 1977.

Naftali Tishby, Fernando C. Pereira, and William Bialek. The information bottleneck method. In Proceedings of the 37th Annual Allerton Conference on Communication, Control, and Computing, pages 368–377, 1999.

Laurens van der Maaten and Geoffrey Hinton. Visualizing data using t-SNE. Journal of Machine Learning Research, 9:2579–2605, 2008.

Heinz von Foerster. Observing Systems. Intersystems Publications, Seaside, CA, 1981.

Alexander D. Wissner-Gross and Cameron E. Freer. Causal entropic forces. Physical Review Letters, 110(16):168702, 2013.

Stephen Wolfram. Universality and complexity in cellular automata. Physica D: Nonlinear Phenomena, 10(1-2):1–35, 1984.

Stephen Wolfram. A New Kind of Science. Wolfram Media, 2002.

Yaodong Yu, Kwan Ho Ryan Chan, Chong You, Chaobing Song, and Yi Ma. Learning diverse and discriminative representations via the principle of maximal coding rate reduction. In Advances in Neural Information Processing Systems, volume 33, 2020.

Table 2: Sampling and reservoir settings for the elementary cellular automata.
<table><tr><td colspan="2">Sampling</td><td colspan="2">Reservoir</td></tr><tr><td>Lattice width</td><td>64</td><td>Feature map</td><td>circular 1D convolution</td></tr><tr><td>Boundary conditions</td><td>circular</td><td>Depth</td><td>3</td></tr><tr><td>Initialization</td><td>Bernoulli(1/2)</td><td>Channels</td><td>256</td></tr><tr><td>Burn-in steps</td><td>1000</td><td>Kernel size</td><td>3 (1 in the final layer)</td></tr><tr><td>Stacked target window</td><td>τ = 32</td><td>Activation</td><td>ELU</td></tr><tr><td>Samples per rule N</td><td>512</td><td>Ridge λ</td><td>0.03</td></tr></table>

Table 3: Reservoir feature maps used as bounded observers. Every map places a pre-activation normalization before each nonlinearity, holding it at the edge of chaos independent of depth and architecture (Appendix A.3).
<table><tr><td>Data geometry</td><td>Feature map φ</td><td>Settings</td></tr><tr><td>1D cellular automata</td><td>circular 1D convolution</td><td>256 channels, kernel 3 (1 in the final layer), ELU; depth 3,  $\lambda ~ = ~ 0 . 0 3$  (ECA ranking); depth 4, λ = 0.3 (inverse NCA)</td></tr><tr><td>Continuous-time flows</td><td>random MLP</td><td>depth 4, width 64, ELU, λ = 0.1</td></tr><tr><td>Flattened images (MNIST encoder)</td><td>random MLP</td><td>depth 4, width 2048, ELU, λ = 3, η = 30</td></tr><tr><td>RL observation trajectories</td><td>random MLP</td><td>depth 4, width 32, ELU, λ = 0.3</td></tr></table>

## A Architectures and sampling

## A.1 Elementary cellular automata

There are 256 elementary rules in total; after removing those equivalent under the left–right reflection and the $0  1$ colour swap, 88 locally unique rules remain (the constant rule 0 among them), and these are the ones scored in the main text. Each elementary rule r has a binary update map $F _ { r }$ acting on a width-64 line with circular boundary conditions. For each rule we draw 512 independent initial states $x _ { i } ^ { ( 0 ) }$ ∼ Bernoulli(1/2), evolve each for a 1000-step burn-in so that it lands on the rule’s attractor, and take as target the stacked window of its next 32 one-step states,

$$
x _ { i } = F _ { r } ^ { 1 0 0 0 } \big ( x _ { i } ^ { ( 0 ) } \big ) , \qquad Y _ { i } = \big ( F _ { r } ( x _ { i } ) , F _ { r } ^ { 2 } ( x _ { i } ) , . . . , F _ { r } ^ { 3 2 } ( x _ { i } ) \big ) ,
$$

where $F _ { r } ^ { k }$ denotes $k$ applications of the rule. We repeat the scoring ten times per rule, each time redrawing both the random reservoir weights and the input ensemble, and report the mean and standard deviation of the resulting epiplexity. Table 2 lists these settings together with the reservoir used to score them.

## A.2 Reservoir feature maps

The bounded observer is a fixed, randomly initialized reservoir whose architecture matches the data geometry. Table 3 lists the configurations used in this paper.

## A.3 Reservoir criticality: a pre-activation normalization at the edge of chaos

The reservoir is random and untrained, so unlike a learned network nothing during fitting moves it toward a useful representation: whether its nonlinearity is engaged at all is decided by its initialization and by the scale of its input. A plain random feedforward stack is a poor default here. Driven by an O(1) input, the pre-activations of a depthfour ELU reservoir have a standard deviation of only a few tenths, so each ELU operates near the origin where it is indistinguishable from a linear map, and the feature map it computes is close to a random linear projection. The operating point is also unstable: it drifts with depth and shifts by orders of magnitude with the input scale, so one architecture can be nearly linear in one experiment and saturated in another.

For recurrent reservoirs the analogous question is settled by the echo-state property and the spectral radius. The underlying principle is that a reservoir is most expressive at the edge of chaos, the boundary between an ordered regime where signals contract and a chaotic one where they explode [Langton, 1990, Packard, 1988]. We define the order parameter as the per-layer perturbation multiplier

$$
\chi = \mathbb { E } \frac { \lVert \delta h ^ { ( \ell + 1 ) } \rVert } { \lVert \delta h ^ { ( \ell ) } \rVert } ,\tag{13}
$$

a  
![](images/1b858dffd5bda1266f35442f9c0886e2ff1e4800d878712ee5112ffd5866754f.jpg)

b  
![](images/49c589a2c5fa30f39afea6e7c41bbfdb65cd114734bc0f8806a0045796f9d437.jpg)

c  
![](images/5c715a998572d40f2e96f849689a23202a571cf030a9c73bbc455fa5fd25c17c.jpg)  
Figure 5: A pre-activation normalization holds a random reservoir at the edge of chaos. (a) Bulk criticality χ against depth for MLP, 1D-, and 2D-convolutional reservoirs: the plain reservoir (dashed) sits in the ordered phase, well below one, while the normalized one (solid) holds at $\chi \approx 1$ for every architecture and depth. (b) Signal survival through depth, the relative norm of an input perturbation by layer: the plain reservoir contracts it exponentially, the normalized one preserves it. (c) Bulk χ against the normalization gain for four activations; gain one reaches $\chi \approx 1$ for all of them.

the factor by which an infinitesimal input perturbation grows from one layer to the next [Poole et al., 2016, Schoenholz et al., $2 0 1 7 ] \colon \chi < 1$ is the ordered phase, where signal and gradients vanish with depth, $\chi > 1$ the chaotic phase, and $\chi \approx 1$ the edge of chaos. Measured by finite differences, the plain reservoir sits in the ordered phase for every architecture we test, at $\chi \approx 0 . 5 5$ for depths up to sixteen and rising $\mathrm { t o } \ \chi \approx 0 . 7 5$ at depth thirty-two, always well below criticality.

We find that a single rule suffices to hold the reservoir at the edge of chaos: normalize the pre-activations over the feature (channel) axis immediately before every nonlinearity. Fixing the pre-activation scale to unit variance places each nonlinearity in its responsive region and pins $\chi$ to a value the activation alone sets, independent of depth, input scale, and architecture (Figure 5).

## A.4 Trainable systems

The neural cellular automaton, the MNIST encoder, and the reinforcement-learning policy are the systems trained to maximize learnable novelty. Table 4 lists their architectures and optimization settings; the reservoirs they are scored against are in Table 3.

Table 4: Trainable systems and their optimization settings.
<table><tr><td colspan="2">Neural cellular automaton  $( x _ { t + 1 } = \mathrm { n o r m a l i z e } ( x _ { t } + g _ { \theta } ( x _ { t } ) )$  , circular boundary)</td></tr><tr><td>Lattice width</td><td>64</td></tr><tr><td>Lift convolution</td><td>radius 2 (kernel 5) to 128 channels, batch normalization, GELU</td></tr><tr><td>Hidden layer</td><td>one pointwise convolution with batch normalization and GELU</td></tr><tr><td>Output projection</td><td>pointwise convolution to the two state channels</td></tr><tr><td>Burn-in steps</td><td>32 (no gradient tracking)</td></tr><tr><td>State noise Stacked target window</td><td>Gaussian, standard deviation 0.1, added after burn-in  $\tau = 8$ </td></tr><tr><td>Batch size</td><td>2048</td></tr><tr><td>State constraint</td><td>two-channel field, unit norm per site</td></tr><tr><td>Optimizer</td><td>AdamW with cosine annealing, learning rate  $1 \times 1 0 ^ { - 4 } , S ^ { \phi }$ </td></tr><tr><td></td><td>by 1/100 before the gradient step</td></tr><tr><td>Gradient clipping Training steps</td><td> $0 . 5$  2,000</td></tr><tr><td colspan="2">MNIST encoder (code  $z = E _ { \theta } ( x ) ,$ </td></tr><tr><td>Encoder  $E _ { \theta }$ </td><td>no labels) trainable MLP with hidden widths 64, 128, 256 and code dimen-</td></tr><tr><td>Code constraint</td><td>sion  $D = 6 4$  unit norm,  $z / \lVert z \rVert$ </td></tr><tr><td>Batch size</td><td>128</td></tr><tr><td>Optimizer Training steps</td><td>AdamW with cosine annealing 500</td></tr><tr><td></td><td></td></tr><tr><td colspan="2">Reinforcement-learning policy (PPO, default MLP policy)</td></tr><tr><td>Algorithm</td><td>PPO [Schulman et al., 2017, Raffin et al., 2021]</td></tr><tr><td>Parallel environments</td><td>8</td></tr><tr><td>Rollout length</td><td>1024</td></tr><tr><td>Minibatch</td><td>256</td></tr><tr><td>Discount  $\gamma$ </td><td>0.999</td></tr><tr><td>GAE  $\lambda _ { \mathrm { G A E } }$ </td><td>0.98</td></tr><tr><td>Learning rate</td><td> $3 \times 1 0 ^ { - 4 }$ </td></tr><tr><td>Training steps</td><td> $6 0 0 { , } 0 0 0$ </td></tr></table>

For the neural cellular automaton, $g _ { \theta }$ denotes the convolutional stack in Table 4, and normalize divides the twochannel vector at each lattice site by its Euclidean length, normalize $\mathbf { \phi } ( v ) _ { i } = v _ { i } / \lVert v _ { i } \rVert$ over the two channels at site i, so every site lies on the unit circle. The main-text run uses the residual normalized update, which keeps a skip connection before the unit-norm projection,

$$
\boldsymbol x _ { t + 1 } = \mathrm { n o r m a l i z e } \left( \boldsymbol x _ { t } + \boldsymbol g _ { \boldsymbol \theta } ( \boldsymbol x _ { t } ) \right) .
$$

A direct variant drops the skip connection and normalizes the convolutional output alone,

$$
x _ { t + 1 } = \mathrm { n o r m a l i z e } \left( g _ { \theta } ( x _ { t } ) \right) .
$$

For both update forms, training samples unit-norm two-channel initial states on a width-64 ring, applies 32 no-gradient burn-in steps, and adds independent Gaussian noise of standard deviation 0.1 at every site of the burned-in state; the stacked future window $Y \overset { \bullet } { = } \left( G _ { \theta } ( X ) , \ldots , G _ { \theta } ^ { \tau } ( X ) \right)$ is rolled out and scored from this perturbed state. Without the perturbation, a run that settles onto a spatially uniform fixed point presents the reservoir with a constant input–target pair, whose score is zero and provides no gradient to escape it. Figure 6 holds the architecture, optimizer, and target window fixed and contrasts the two update rules, training each from nine independent random seeds. Both rules develop coherent traveling structures across all nine seeds

## B Robustness of the elementary-cellular-automaton ranking

The ranking of Figure 2 is computed under the fixed estimator configuration of Table 2. To test how much of it depends on that choice, we vary one hyperparameter at a time around the reference configuration and re-score all 88 rules: the resolution $\eta \in [ 0 . 0 3 , 3 0 ]$ , the ridge penalty $\lambda \in [ 0 . 0 0 1 , 1 ]$ , the target window length $\tau \in \{ 4 , \dots , 6 4 \}$ , the reservoir depth $\in \{ 1 , \ldots , 5 \}$ , kernel $\mathrm { s i z e } \in \{ 3 , 5 , 7 \}$ , channel count $\in \{ 6 4 , \ldots , 5 1 2 \}$ , and the sample count $\textit { N } \in$ {128, . . . , 1024}. Each configuration is scored with a single draw of the reservoir weights and input ensemble; the reference configuration, every configuration at which the top rank changes, and every configuration at which the score order of rules 30 and 54 flips are re-scored with three independent draws.

![](images/8016f6106310528cff2aa6d54fcd212f15652d8f0cd480c68660e41b0fe45859.jpg)  
Figure 6: Final NCA evolution under the direct and residual update rules, each over nine random seeds, with the architecture and target window held fixed. The upper three rows use the direct normalized update, the lower three the residual update; the nine cells of each block are nine independent seeds. Every panel shows a final-checkpoint rollout and annotates its final $S ^ { \phi }$ . Both rules develop coherent traveling structures across all nine seeds, with final scores in a narrow band.

Rule 110 keeps the top rank across the entire tested range of every axis except the two that cut the observer or the target window below the scale of its structure (Figure 7a). At the reference configuration its margin over the best other rule (rule 25) is 20.7 bits over three draws, and the margin stays between 9.6 and 28.4 bits at every other configuration where it is first. The full ranking is similarly rigid: its Spearman correlation with the reference ranking stays above 0.90 everywhere except at depth ≤ 2. The first exception is τ = 4, where the window is too short for the accumulated structure of rule 110 to separate it from the field and it falls 0.5 bits behind rule 73 (18.2±0.4 against 18.7±0.2, threedraw means). The second is small depth: at depth 2 the reservoir’s receptive field has radius one and rule 25 overtakes rule 110 (13.5 ± 0.4 against 10.4 ± 0.5 bits), and at depth 1 the reservoir sees a single cell and the measurement collapses altogether (rule 110 falls to rank 40 and the correlation with the reference ranking vanishes).

![](images/6f8dda1b14342572f843fbdef09f6172085d967eddbe71decfbdc8f6f5908d7c.jpg)  
Figure 7: One-at-a-time robustness of the ECA ranking. In both panels each row varies one estimator hyperparameter around the reference configuration of Table 2 (outlined column), with columns aligned by step offset from the reference value. (a) Margin, in bits, between rule 110’s epiplexity and that of the best other rule; each cell prints the value scored, so a positive (blue) cell is a configuration at which rule 110 ranks first, and in the cells where it is not first the cell adds rule 110’s rank in bold (single draw). (b) Ranks of the reference rules 30 (chaotic, before the slash) and 54 (complex, after the slash) under the same scan; color gives their difference, blue where rule 54 ranks above rule 30 and red where rule 30 ranks above rule 54, saturated at ±15.

The reference rules 30 and 54 order themselves by the observer’s locality (Figure 7b). At the reference configuration the complex rule 54 ranks fourth and the chaotic rule 30 twelfth, with a score gap $S _ { 5 4 } ^ { \phi } - S _ { 3 0 } ^ { \phi } = 1 0 . 9 \pm 1 . 0$ bits over three draws, and this order holds across the full tested range of the resolution, ridge, window, channel, and sample axes. It reverses exactly where the receptive field grows beyond radius two: one more layer (depth 4, radius three) puts rule 30 fifth and rule 54 thirteenth (gap −14.6 ± 1.0 bits), and a wider kernel (kernel 5, radius four) does the same (−11.9 ± 0.5 bits). An observer of radius at most two prices the structured rule above the chaotic one; a wider view makes the chaotic rule’s short-range structure learnable and reverses the order. Rule 110 ranks first in both regimes.

## C The log-determinant description length as a matrix-t marginal

The main text prices the readout directly by the spectral description length equation 6. The same form arises from a hierarchical Gaussian prior. Let $W \in \mathbb { R } ^ { \mathbf { \check { \ b { m } } } \times \mathbf { \check { \ b { D } } } }$ and make its conditional law matrix Gaussian,

$$
\begin{array} { r } { W \mid \Lambda \sim \mathcal { M N } _ { m , D } \big ( 0 , \Lambda ^ { - 1 } , I _ { D } \big ) , \qquad p ( W \mid \Lambda ) \propto \mid \Lambda \mid ^ { D / 2 } \exp \Big ( - \frac { 1 } { 2 } \operatorname { t r } \big ( \Lambda W W ^ { \top } \big ) \Big ) , } \end{array}\tag{14}
$$

with $\Lambda \succ 0$ a row precision matrix. Holding the precision fixed at $\Lambda = \lambda I _ { m }$ collapses the negative log-density, in bits, to a quadratic,

$$
- \log _ { 2 } { p ( W \mid \lambda I _ { m } ) } = C + \frac { \lambda } { 2 \ln 2 } \| W \| _ { F } ^ { 2 } ,\tag{15}
$$

the ridge penalty. If instead the precision is not specified in advance but given an isotropic Wishart-type hyperprior $p ( \Lambda ) \propto | \Lambda | ^ { ( a - m - 1 ) / 2 } \exp \big ( - { \textstyle { \frac { 1 } { 2 \eta } } } \mathrm { t r } \Lambda \big )$ , with $a > m - 1$ so that the prior is proper and the integrals below converge, the marginal density of W is $\begin{array} { r } { p ( W ) = \int _ { \Lambda \sim 0 } p ( W \mid \Lambda ) p ( \Lambda ) d \Lambda } \end{array}$ . Collecting the powers and exponential terms in Λ,

$$
p ( W ) \propto \int _ { \Lambda \sim 0 } \vert \Lambda \vert ^ { ( a + D - m - 1 ) / 2 } \exp \Big [ - \textstyle \frac { 1 } { 2 } \mathrm { t r } \left( ( W W ^ { \top } + \eta ^ { - 1 } I _ { m } ) \Lambda \right) \Big ] d \Lambda ,\tag{16}
$$

and applying the Wishart integral identity $\begin{array} { r } { \int _ { \Lambda \sim 0 } | \Lambda | ^ { ( \nu - m - 1 ) / 2 } \exp \big ( - \frac { 1 } { 2 } \operatorname { t r } ( A \Lambda ) \big ) d \Lambda \propto | A | ^ { - \nu / 2 } } \end{array}$ with $\nu = a + D$ and $\boldsymbol { A } = \boldsymbol { W } \boldsymbol { W } ^ { \top } + \eta ^ { - 1 } \boldsymbol { I _ { m } }$ gives

$$
p ( W ) \propto \operatorname * { d e t } \bigl ( W W ^ { \top } + \eta ^ { - 1 } I _ { m } \bigr ) ^ { - ( a + D ) / 2 } \propto \operatorname * { d e t } \bigl ( I _ { m } + \eta W W ^ { \top } \bigr ) ^ { - ( a + D ) / 2 } .\tag{17}
$$

Dropping the constants independent of W ,

$$
- \log _ { 2 } { p ( W ) } = C + \frac { a + D } { 2 } \log _ { 2 } \operatorname* { d e t } \bigl ( I _ { m } + \eta W W ^ { \top } \bigr ) ,\tag{18}
$$

which is the spectral description length equation 6 with $\alpha = ( a + D ) / 2$ . The log-determinant form is therefore the description length of the Gaussian readout after the unknown precision has been integrated out: the ridge penalty corresponds to a fixed precision, the log-determinant to a marginalized one. The marginalization supplies the form of the description length; the estimator treats α as a free overall scale and fixes $\alpha = 1 / 2$ throughout, rather than the D-dependent value the hierarchical derivation would assign.

## D Exact minimization of the description length

The main text fits the readout by a ridge approximation to the total description length (Section 3). This appendix minimizes the objective directly, without the approximation:

$$
\mathcal { I } _ { \mathrm { M D L } } ( W ) = \frac { 1 } { 2 \sigma ^ { 2 } \ln 2 } \| \tilde { Y } - \tilde { H } W \| _ { F } ^ { 2 } + \mathcal { C } _ { \mathrm { s p e c } } ( W ) ,\tag{19}
$$

with $\mathcal { C } _ { \mathrm { s p e c } }$ the spectral description length equation 6 and the residual scale calibrated as $\sigma ^ { 2 } = \lambda / ( 2 \alpha \eta )$ , so that the two objectives coincide in the small-readout regime, where log det $\begin{array} { r } { ( I _ { m } + \eta W W ^ { \top } ) \approx \eta \| W \| _ { F } ^ { 2 } } \end{array}$ and the spectral description length reduces to the ridge penalty. We write $S _ { \mathrm { M D L } } ^ { \phi }$ for the spectral description length of the exact optimum $W _ { \mathrm { M D L } }$

The objective has no closed-form minimizer, but the log-determinant is concave in $W W ^ { \top }$ , so its linearization at the current iterate is a global upper bound on the description length, and minimizing that bound is a weighted ridge solve:

$$
\begin{array} { l l } { { W _ { k + 1 } ~ = ~ \left( \tilde { H } ^ { \top } \tilde { H } + \lambda M _ { k } \right) ^ { - 1 } \tilde { H } ^ { \top } \tilde { Y } , ~ } } & { { ~ M _ { k } ~ = ~ \left( I _ { m } + \eta W _ { k } W _ { k } ^ { \top } \right) ^ { - 1 } . } } \end{array}\tag{20}
$$

Each sweep of this majorize–minimize iteration decreases $\mathcal { I } _ { \mathrm { M D I } }$ monotonically. Warm-started at $W _ { \lambda }$ and run in double precision on the sufficient statistics, it converges to a stationary point; rescaling the warm start by factors between $1 / 4$ and 4 leaves the solution unchanged.

Figure 8 compares the two readouts on identical reservoirs and data. The exact minimizer extracts more bits from the same data: across the 88 elementary rules (ten reservoir and data draws each, the setting of Table 2), $S _ { \mathrm { M D L } } ^ { \phi }$ exceeds $S ^ { \phi }$ by a factor growing from about 1 to about 2.3 with the score itself, because the log-determinant description length is flatter than the quadratic penalty at large singular values and lets the readout reach further into faintly expressed directions. The excess is one-sided: under an isotropic feature Gram every stationary point of equation 19 satisfies w $\big ( 1 + \lambda / ( 1 + \eta w ^ { 2 } ) \big ) = \sigma$ along each singular direction and so shrinks less than the ridge solution $\sigma / ( 1 + \lambda )$ , giving $S ^ { \phi } \le S _ { \mathrm { { M D L } } } ^ { \phi }$ ; the measured Gram is far from isotropic, but the ordering holds in every paired solve we ran (880 for the $\mathrm { E C A }$ , 99 for the NCA). Yet the two readouts rank systems almost identically: Spearman $\rho = 0 . 9 9 7$ over the rules, the same top-fourteen set, rule 110 maximal under both with its margin over the runner-up widening from 24.7 to 38.7 bits, and the largest rank change anywhere is rule 41, second under the ridge readout and thirteenth under the exact one; on the inverse-NCA trajectories (three seeds, eleven checkpoints each) the two scores move together (Pearson $r = 0 . 9 9 6 )$ , with a nearly constant 35-bit offset on the converged plateau. Removing the approximation changes how many bits the observer extracts, not which systems it finds structured; the estimator therefore keeps the ridge readout.

![](images/810176c9dbc143a7c1b580aed749e2f276fd32cdac49cffc9b011a60ed7faba3.jpg)

![](images/39d9d36055239b143b35f0429ccd5f226052eaaa432b1311e5b5828c4b164980.jpg)  
Figure 8: The ridge readout against the exact minimizer of the description length, on identical reservoirs and data. (a) Per-rule mean scores for the 88 elementary rules: the reported $S ^ { \hat { \phi } }$ (the spectral description length of the ridge readout $W _ { \lambda } )$ against $S _ { \mathrm { M D L } } ^ { \phi }$ (that of the minimizer of equation 19). Error bars are standard deviations over ten reservoir and data draws; the dashed line is the identity; red marks the five highest rules under $S _ { \mathrm { M D L } } ^ { \phi }$ , and rule 41 is the largest rank change (second to thirteenth). (b) The same comparison at every checkpoint of the three inverse-NCA training runs (marker shape: seed; colour: training step; error bars: standard deviations over three evaluation draws).

## E Numerically stable, differentiable ridge solve

The estimator in equation 9 is defined through the ridge optimum $W _ { \lambda } = ( \tilde { H } ^ { \top } \tilde { H } + \lambda I _ { m } ) ^ { - 1 } \tilde { H } ^ { \top } \tilde { Y }$ . Solving it the textbook way, by forming the Gram matrix $\tilde { H } ^ { \top } \tilde { H }$ and inverting (the normal equations), squares the conditioning of the design matrix, turning a condition number $\kappa ( \tilde { H } )$ into $\kappa ( \tilde { H } ) ^ { 2 }$ . In single precision this is not a minor loss: whenever the reservoir features are nearly collinear, which is exactly the low-epiplexity regime where the bounded readout find little independent structure to use, the squared conditioning corrupts $W _ { \lambda }$ and therefore the score. Because the inverse experiments drive the generating system across a wide range of feature conditioning, an unstable solve distorts both $S ^ { \phi }$ and the gradient the optimization follows.

The batch solve therefore never forms the Gram matrix. For output coordinate $j ,$ writing the ridge objective as a single least-squares problem gives

$$
\big \| \tilde { H } w _ { j } - \tilde { y } _ { j } \big \| _ { 2 } ^ { 2 } + \lambda \| w _ { j } \| _ { 2 } ^ { 2 } \ = \ \bigg \| \bigg [ \frac { \tilde { H } } { \sqrt { \lambda } I _ { m } } \bigg ] w _ { j } - \bigg [ \frac { \tilde { y } _ { j } } { 0 _ { m } } \bigg ] \bigg \| _ { 2 } ^ { 2 } ,\tag{21}
$$

where $\tilde { y } _ { j }$ is column $j$ of $\tilde { Y }$ . The ridge optimum is the ordinary least-squares solution of the augmented system with design matrix $\tilde { H } _ { \mathrm { a u g } } = [ \tilde { H } ; \sqrt { \lambda } I _ { m } ] \in \mathbb { R } ^ { ( N + m ) \times m }$ and target $\tilde { y } _ { j , \mathrm { a u g } } = \left[ \tilde { y } _ { j } ; \ : 0 _ { m } \right]$ . We solve this with a reduced QR factorization $\tilde { H } _ { \mathrm { a u g } } = Q R$ followed by a triangular solve,

$$
w _ { j } = R ^ { - 1 } Q ^ { \top } \tilde { y } _ { j , \mathrm { a u g } } ,\tag{22}
$$

and stacking the column solutions gives $W _ { \lambda } = [ w _ { 1 } , \dots , w _ { D } ]$ . This operates on the design matrix directly. The effective conditioning is that of $\tilde { H } _ { \mathrm { a u g } } ,$ , the square root of what the normal equations would face, and the whole computation stays in the input dtype without ever materializing $\tilde { H } ^ { \top } \tilde { H }$ . The $\sqrt { \lambda } I _ { m }$ block gives $\tilde { H } _ { \mathrm { a u g } }$ full column rank for any $\lambda > 0 ,$ , so R is invertible and the solve is well posed even when H<sup>˜</sup> is itself rank-deficient.

This solve is differentiable. Both the QR factorization and the triangular solve have well-defined derivatives, so $W _ { \lambda }$ (and hence the spectral score $\begin{array} { r } { S ^ { \phi } = \alpha \log _ { 2 } \operatorname* { d e t } ( I _ { m } + \eta W _ { \lambda } W _ { \lambda } ^ { \top } ) } \end{array}$ , whose singular-value decomposition is likewise differentiable) is a differentiable function of $\tilde { H }$ and $\tilde { Y }$ , and through the normalization and the frozen reservoir $\phi ,$ of the data $( X , Y )$ . In the inverse experiments we backpropagate $S ^ { \phi }$ through exactly this computation into the parameters of the system that generates (X, Y ), with ϕ held fixed. The closed-form solve therefore serves both as a cheap forward score and as a differentiable layer in the optimization.

## F Reservoir epiplexity on continuous-time flows

The same closed-form score, with its reservoir an MLP on the state vector, ranks a further family of dynamical systems, continuous-time flows, consistently with a longstanding qualitative classification.

## F.1 Continuous-time chaotic systems

For continuous-time flows we use the same random MLP reservoir as the other feedforward experiments: a four-layer network with ELU activations, hidden width 64, and ridge penalty $\lambda = 0 . 1$ . Each sample pairs an attractor state x with a stacked window of its future: we draw a random initial condition, integrate the system for a burn-in time of 0.5 to reach the attractor, and record the state as $x ;$ Rossler and Thomas receive a longer initial integration before this¨ burn-in (a pre-burn-in), because their attractors lie far from the region where initial conditions are drawn and the 0.5- unit burn-in alone would not reach them; then we snapshot the trajectory at the ten lead times $0 . 1 , 0 . 2 , \ldots , 1 . 0$ from x and stack them as the target window $y .$ Both x and every target snapshot are standardized per state dimension by the empirical mean and standard deviation of the ensemble of x, so the attractor’s absolute scale does not enter the score. The reservoir maps x to features and one ridge readout per snapshot predicts the whole window; the epiplexity is the program length of the stacked readout, scored as in equation 9. We draw 512 samples per system and average the score over eight independent draws of the reservoir weights.

Across three chaotic systems (Lorenz, Rossler, Thomas) and three two-dimensional linear systems (pure rotation,¨ damped spiral, stable node), the chaotic systems score well above the linear baselines (Figure 9). Lorenz scores highest at 46, with Rossler at ¨ 25 and Thomas at 17; all three sit well above the linear systems, which fall between 6.9 and 8.4.

## F.2 Temporal accumulation of epiplexity

The cross-system comparison above draws independent state pairs from an ensemble of initial conditions. In the reinforcement-learning setting, where a dense per-step reward is needed, we instead track how epiplexity accumulates along a single trajectory as observations arrive one by one. Given a trajectory $x _ { 0 } , x _ { 1 } , \ldots , x _ { N }$ sampled at interval $\Delta t _ { s } ,$ define the cumulative epiplexity $S _ { t } ^ { \phi }$ as the score computed from all pairs $( x _ { i } , y _ { i } )$ with $i \le t - \tau$ , where $y _ { i }$ is the future window stacked from step i and τ its horizon in samples. Each new observation adds one pair to the ridge regression; the marginal contribution $\xi _ { t } = S _ { t } ^ { \phi } - S _ { t - 1 } ^ { \phi }$ measures how much learnable structure the latest state brings.

Recomputing the ridge readout from scratch at every step costs $O ( N ^ { 2 } m ^ { 2 } )$ for a length-N stream. The same quantity admits an exact recursive least-squares form: maintaining the inverse Gram matrix and the readout under a Sherman– Morrison rank-1 update advances each step in $O ( m ^ { 2 } )$ , plus $O ( m ^ { 2 } D )$ for the singular values of the $m \times D$ readout whenever the score itself is evaluated. Unlike the batch QR solve of Appendix E, this covariance form does maintain the inverse Gram matrix and so gives up that solve’s conditioning advantage; at the small reservoir widths used online (m = 32) this is numerically benign.

## G Additional details for the inverse experiments

## G.1 Neural cellular automaton

With the architecture and optimization settings of Table 4, the score climbs from its low initial value over the first several hundred steps, then rises more gradually and levels onto a plateau by about step 1,500, ending between $S ^ { \phi } = 8 6$ and 89 across the three seeds of the residual $\tau = 8$ run shown in Figure 3. The traveling structures emerge early in the climb and, once formed, persist through the remainder of training. Rolling the final checkpoint out from a fresh random initial state on a wider lattice preserves the same regime beyond the training width, indicating that the learned local rule has not simply memorized the training-time lattice size.

![](images/97b9ac1685e3d0529a46285c7ad23df55ea8fe895833beca973ddec07e759d4f.jpg)  
Figure 9: MLP-reservoir epiplexity on continuous-time systems. (a) The chaotic systems (Lorenz, Rossler, Thomas)¨ score well above the linear baselines. (b) Phase portraits of the six systems, eight initial conditions each.

## G.2 MNIST encoder

The ridge regularizer λ controls how tight the readout bound is and therefore which encoders qualify as high-epiplexity. We use $\lambda = 3$ , far above the values typical of reservoir computing $( 1 0 ^ { - 5 }$ or smaller): a tight bound is what keeps redundancy expensive and forces the encoder toward compressed codes organized by the data’s underlying factors, rather than letting it satisfy a loose readout with arbitrary ones. The raw score grows with both the code dimension D and the reservoir width, but a higher raw score reached by enlarging either does not by itself sharpen the class structure: it lets the encoder satisfy the readout without compressing. We report $D = 6 4$ with a width-2048 reservoir; tightening the bound, rather than enlarging the model, is what selects for natural abstractions.

We test local robustness by varying one hyperparameter at a time around the reported configuration and training each variant for 150 steps with the same seed (Figure 10). Learning rate, batch size, code dimension, and reservoir depth leave the final linear-probe accuracy between 0.80 and 0.90 across their tested ranges. The estimator parameters have a wider failure regime: very weak ridge regularization $( \lambda \leq 0 . 3 )$ or low resolution $( \eta \leq 0 . 1 )$ drives accuracy below 0.5, whereas the neighborhood containing the reported $\lambda = 3$ and $\eta = 3 0$ remains high-accuracy. Thus the result does not depend narrowly on the precise reference values, although the estimator must still impose a sufficiently selective readout.

## H Reinforcement-learning details

## H.1 Reward design

From the observation trajectory $o _ { 0 } , o _ { 1 } , . . .$ . we score, at each step, the map from $o _ { t }$ to the stacked window $( o _ { t + 1 } , \ldots , o _ { t + \tau } )$ of the next τ observations, flattened into a single dτ -dimensional target, using the estimator of Section 3 with a frozen random four-layer MLP reservoir (ELU nonlinearities). The whole-trajectory score $S _ { T } ^ { \phi }$ is

![](images/57b7569c9248a181bfd257c1ea13baeea56eb610091780db77e8f6ded00c1005.jpg)  
Figure 10: One-at-a-time robustness of the MNIST representation experiment. Each cell gives the varied hyperparameter (top) and final linear-probe accuracy after 150 training steps (bottom); all other settings remain at the reference values in the black-outlined column. Columns order the tested values within each row by their offset from the reference. The color scale is fixed from 0 to 1, centered at white for 0.5 accuracy; red marks values below 0.5 and blue values above it.

maintained online by the covariance-form recursive-least-squares estimator (Appendix F.2 gives the recursion), one rank-1 update per step; the per-step reward is the increment $S _ { t } ^ { \phi } - S _ { t - 1 } ^ { \phi }$ , which telescopes to $S _ { T } ^ { \phi }$

## H.2 Reinforcement-learning setup

Input normalization is essential here and specific to the reinforcement-learning setting (the inverse experiments use bounded states and do not need it): an agent’s observation coordinates are unbounded and can differ in scale across observations by orders of magnitude, so we standardize each coordinate (subtracting its random-policy mean and dividing by its standard deviation) before the reservoir, since a large-magnitude input otherwise saturates the fixed nonlinearity in ϕ and the reward stops discriminating. A small reservoir (width 32) is the bounded-learner setting: a wide reservoir can fit even a random or chaotic trajectory, so the epiplexity bonus would reward chaos; a narrow one can only fit structured trajectories, so it rewards coherent, regular motion. The window horizon τ is a fixed per-task constant, on the order of twice the characteristic time over which the state changes appreciably under a random policy, kept within [8, 48]. Per task this gives (state dimension d, horizon τ ): Acrobot (6, 8), MountainCarContinuous (2, 28), Hopper (11, 10), BipedalWalker (24, 40), HalfCheetah (17, 16), LunarLander (8, 48), Walker2d (17, 16), Swimmer (8, 16), Pendulum (3, 16), PointMaze (8, 48). The reservoir ridge is λ = 0.3. The PointMaze observation is the flattened goal-conditioned dictionary, and the goal resamples on contact (continuing task) so reaching it does not end the episode.

## H.3 Training

We use PPO [Schulman et al., 2017, Raffin et al., 2021] with 8 parallel environments, rollout length 1024, minibatch $2 5 6 , \gamma = 0 . 9 9 9 , \mathrm { G A E } \lambda _ { \mathrm { G A E } } = 0 . 9 8$ , learning rate $3 \times 1 0 ^ { - 4 }$ , for 600,000 steps, on the default MLP policy, reporting the mean over ten seeds. In the mixed mode the bonus weight β is calibrated per environment so the bonus’s whole-episode contribution is 0.1 times the random-policy task-return scale (anchored at the episode level so it survives sparse rewards, where a per-step calibration to a near-zero reward would vanish). The state-magnitude control uses the identical setup, with the per-step bonus the squared norm $\| \big ( o _ { t } - \mu _ { o } \big ) \odot \sigma _ { o } ^ { - 1 } \| ^ { 2 }$ of the input-normalized state in place of the epiplexity increment; it is run on all ten tasks of Table 1. The reported return is the task return over 100 evaluation episodes, which the epiplexity-only agent never observes during training.

On the sparse and deceptive classic-control tasks the gain is not only in the mean but in reliability: PPO on the task reward alone solves Acrobot and MountainCarContinuous only on some seeds and fails catastrophically on others (across-seed standard deviation ≈ 166 and 43 in task-return units), whereas the bonus solves them on every seed (standard deviation ≈ 2). The bonus turns unreliable exploration into reliable solving. On the locomotion tasks it lifts the mean return (Hopper most, then HalfCheetah, BipedalWalker, and Swimmer), helping PPO escape mediocre local optima. It is rarely harmful: at the same 600,000-step budget the bonus also raises LunarLander’s return (by 23%) and Pendulum’s slightly, and only on Walker2d, where the task reward already affords adequate exploration, does it mildly lower the mean (by 4%). The pattern matches the mechanism: the bonus helps exactly when covering observed state is the bottleneck, and the learnable-novelty drive is a mild distraction when it is not.

The state-magnitude control shows that the stability of the bonus is specific to learnable novelty and not shared by raw magnitude. It collapses LunarLander from a return of 169 to −171: a near-constant coordinate (the leg-contact indicators, which a random policy almost never triggers, so their estimated standard deviation is tiny) gives the inputnormalized magnitude an enormous spike whenever a leg touches down, and the agent is driven toward that spike instead of toward a soft landing. On Walker2d both the magnitude control and the epiplexity bonus sit essentially at the baseline (294 and 285 against 296), neither helping nor collapsing, and on Pendulum the magnitude control leaves the return essentially unchanged. Across all ten tasks the epiplexity bonus falls at most 4% below the task reward and collapses on none, whereas the magnitude control collapses on two (Hopper and LunarLander). Raw magnitude has no principled scale, so a single degenerate coordinate can hijack it; epiplexity instead prices each coordinate by how well a bounded readout predicts it, which is what makes it stable where the magnitude bonus is not.