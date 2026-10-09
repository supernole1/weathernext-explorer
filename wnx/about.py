"""'About WeatherNext' explainer shown (collapsed) at the top of each report."""

ABOUT_HTML = """
<details style="border:1px solid #e6e5e0;border-radius:8px;padding:10px 18px;margin:12px 0;background:#fff">
<summary style="cursor:pointer;font-weight:600;font-size:16px">What is WeatherNext 3? (Google, DeepMind and AI weather forecasting)</summary>
<div style="line-height:1.55;color:#52514e">

<h4 style="color:#0b0b0b;margin:14px 0 4px">Who makes it: Google DeepMind</h4>
<p style="margin:0 0 8px">DeepMind is an artificial-intelligence research lab founded in London in 2010. Google bought it in 2014,
and in 2023 it merged with Google's own AI group (Google Brain) to become <b>Google DeepMind</b>, the main AI lab of
Google and its parent company Alphabet. It is best known for <b>AlphaGo</b> (the first program to beat a world champion
at Go), <b>AlphaFold</b> (which predicts protein shapes and earned its creators a share of the 2024 Nobel Prize in
Chemistry) and Google's <b>Gemini</b> AI models. Weather forecasting is one of its science projects.</p>

<h4 style="color:#0b0b0b;margin:14px 0 4px">How AI forecasting differs from traditional forecasting</h4>
<p style="margin:0 0 8px">Traditional models, like the American GFS and the European ECMWF, simulate the atmosphere with
physics equations. They need hours on a supercomputer for each run. DeepMind's models instead <i>learned</i> how
weather evolves by studying about 40 years of historical global weather data. Once trained, they produce a full
15-day global forecast in about a minute on Google's AI chips, cheaply enough to run dozens of versions (an
"ensemble") every time. They still start from a traditional weather analysis (a snapshot of current conditions
built from observations). Waiting for that snapshot is the main reason new runs appear roughly 6–7 hours after
their start time.</p>

<h4 style="color:#0b0b0b;margin:14px 0 4px">How does it actually work? (Is it a "storms like this did that" model?)</h4>
<p style="margin:0 0 6px">Not really. The old <b>statistical/analog</b> models look up history: "storms at this latitude,
moving this way in October, usually went here." NHC still runs simple ones (CLIPER, SHIFOR), mainly as a baseline
that real forecasts should beat. WeatherNext 3 works more like <b>a simulator that taught itself the rules</b>:</p>
<ol style="margin:0 0 8px;padding-left:22px">
<li>It takes in the <b>whole atmosphere</b> right now: temperature, wind, humidity and pressure at many heights,
across the entire globe.</li>
<li>A neural network predicts what all of that will look like <b>one hour later</b>.</li>
<li>It feeds that prediction back in and repeats, hour after hour, out to 15 days.</li>
</ol>
<p style="margin:0 0 6px">The storm's path <i>falls out of</i> that simulation. A storm turns because the model
forecasts the high-pressure ridges and troughs that steer it, not because similar storms turned there. No physics
equations were coded in. It learned how the atmosphere behaves from decades of global weather data, much as a
traditional model applies those rules directly.</p>
<p style="margin:0 0 6px"><b>Where it does use storm history:</b> early AI weather models drew hurricanes too weak,
because they smooth out extremes. So the cyclone part was also trained on historical official storm records (track
and intensity) to correct that. Each storm's position and wind numbers are tuned against past storms, but they are
computed from the simulated atmosphere around <i>this</i> storm, not copied from look-alikes.</p>
<ul style="margin:0 0 8px;padding-left:20px">
<li><b>Strength:</b> it learned general atmospheric behavior from all weather, not just storms, so it copes with
unusual setups and is fast enough to run 64 versions every hour.</li>
<li><b>Weakness:</b> truly unprecedented events, with nothing similar in its training data, are where it is least
trustworthy. Physics models don't share that blind spot, one reason NHC weighs both.</li>
<li><b>The 64 ensemble members</b> come from slightly varying the starting conditions and the model itself, not
from sampling 64 past storms.</li>
</ul>

<h4 style="color:#0b0b0b;margin:14px 0 4px">The family tree</h4>
<ul style="margin:0 0 8px;padding-left:20px">
<li><b>GraphCast (2023):</b> DeepMind's first big AI weather model, a single 10-day forecast. In published
tests it beat the leading European model on most measures.</li>
<li><b>GenCast (2024):</b> added ensembles, many possible futures instead of one, out to 15 days.</li>
<li><b>WeatherNext (2025):</b> Google's brand name for these models as products. That year DeepMind launched
<b>Weather Lab</b> and an experimental <b>cyclone model</b>, and began working with the US National Hurricane Center,
which used it as one of its guidance tools during the 2025 season, including for Hurricane Melissa.</li>
<li><b>WeatherNext 2 (late 2025):</b> a faster ensemble model. The <b>OPER</b> (green) line in these reports is
the cyclone model built on this generation.</li>
<li><b>WeatherNext 3 (August 2026):</b> the current model and the <b>WNV3</b> (blue) line here. It is the first global
model to start a new forecast <b>every hour</b>, with detail down to about 5 km at weather stations and 10 km
elsewhere, and 64 ensemble members. Beyond historical weather data, it also learned from satellite rainfall
estimates and real storm and station observations. In DeepMind's tests it improved slightly on WeatherNext 2 for
both hurricane track and intensity.</li>
</ul>

<h4 style="color:#0b0b0b;margin:14px 0 4px">Where you run into it</h4>
<p style="margin:0 0 8px">WeatherNext forecasts feed Google's own weather features (Search, Maps, Pixel phones).
They are also sold and shared through Google Cloud. The cyclone tracks in these reports come free from DeepMind's
public <b>Weather Lab</b> site. The full gridded data (BigQuery, Earth Engine, Cloud Storage) is available to
approved users. DeepMind has also open-sourced the code and weights for its WeatherNext 2 and cyclone models.</p>

<h4 style="color:#0b0b0b;margin:14px 0 4px">The fine print</h4>
<p style="margin:0">Weather Lab data is labeled <b>experimental research data</b>, not an official forecast. In the US,
the National Hurricane Center is the official source for hurricane forecasts and warnings, and your local
emergency managers decide evacuations. Think of WeatherNext as a very good second opinion that NHC itself consults.</p>
</div></details>
"""
