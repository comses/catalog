-- Before Check
-- COPY
-- (SELECT c_pub.id, max(title) AS title, array_agg(DISTINCT c_plat.name ORDER BY c_plat.name) AS platforms, array_agg(DISTINCT c_spons.name ORDER BY c_spons.name) AS sponsors
-- FROM core_publication AS c_pub
--   LEFT JOIN core_publication_platforms AS c_pub_plat ON c_pub.id = c_pub_plat.publication_id
--   LEFT JOIN core_platform AS c_plat ON c_pub_plat.platform_id = c_plat.id
--   LEFT JOIN core_publication_sponsors AS c_pub_spons ON c_pub.id = c_pub_spons.publication_id
--   LEFT JOIN core_sponsor AS c_spons ON c_pub_spons.sponsor_id = c_spons.id
-- GROUP BY c_pub.id)
-- TO '/home/ubuntu/postgres/old_publication_summary.csv'
-- WITH (FORMAT csv, HEADER TRUE, DELIMITER ',');

BEGIN;
SET CONSTRAINTS ALL IMMEDIATE;
CREATE OR REPLACE FUNCTION split_platform(_val TEXT, _new_vals TEXT[]) RETURNS VOID AS
  $$
    DECLARE
      _publication_ids INT[];
      _publication_id INT;
      _platform_id INT;
      _new_platform_id INT;
      _new_val TEXT;
    BEGIN
      SELECT id
      INTO _platform_id
      FROM core_platform
      WHERE name = _val;

      SELECT array_agg(publication_id)
      INTO _publication_ids
      FROM core_publication_platforms
      WHERE platform_id = _platform_id;

      RAISE NOTICE 'platform_id: %', _platform_id;
      RAISE NOTICE 'publication_ids: %', array_to_string(_publication_ids, ',', 'NULL');

      RAISE NOTICE 'deleting old core_platform %', _platform_id;

      DELETE FROM core_publication_platforms
      WHERE platform_id = _platform_id OR platform_id IN
        (SELECT id FROM core_platform WHERE "name" = ANY(_new_vals));

      DELETE FROM core_platform
      WHERE id = _platform_id OR "name" = ANY(_new_vals);

      FOREACH _new_val IN ARRAY _new_vals
      LOOP
        SELECT nextval('core_platform_id_seq') INTO _new_platform_id;

        RAISE NOTICE 'inserted %, % into core_platform', _new_platform_id, _new_val;
        INSERT INTO core_platform (id, "name") VALUES (_new_platform_id, _new_val);

        INSERT INTO core_publication_platforms (publication_id, platform_id)
        SELECT unnest(_publication_ids), _new_platform_id;
      END LOOP;
    END;
  $$ LANGUAGE plpgsql VOLATILE;


CREATE OR REPLACE FUNCTION merge_platform(_platform_names TEXT[], _val TEXT) RETURNS VOID AS
  $$
  DECLARE
    _publication_ids INT[];
    _platform_ids INT[];
    _platform_id INT;
  BEGIN
    SELECT array_agg(id)
    INTO _platform_ids
    FROM core_platform
    WHERE name = ANY(_platform_names);
    RAISE NOTICE '_platform_names: %', array_to_string(_platform_names, ',', 'NULL');
    RAISE NOTICE '_platform_ids: %', array_to_string(_platform_ids, ',', 'NULL');

    SELECT array_agg(DISTINCT publication_id)
    INTO _publication_ids
    FROM core_publication_platforms
    WHERE platform_id = ANY(_platform_ids);

    DELETE FROM core_publication_platforms
    WHERE platform_id = ANY(_platform_ids);

    DELETE FROM core_platform
    WHERE id = ANY(_platform_ids);

    SELECT nextval('core_platform_id_seq') INTO _platform_id;
    INSERT INTO core_platform (id, name) VALUES (_platform_id, _val);

    INSERT INTO core_publication_platforms (publication_id, platform_id)
    SELECT unnest(_publication_ids), _platform_id;
  END;
  $$ LANGUAGE plpgsql VOLATILE;

SELECT split_platform('C#', ARRAY['C#', '.NET']);
SELECT split_platform('C#.NET', ARRAY['C#', '.NET']);
SELECT split_platform('Java Agent-based Simulation Platform (JAS)', ARRAY['Java', 'JVM', 'JAS (Java Agent-based Simulation Platform)']);
SELECT split_platform('Java Agent Development Framework', ARRAY['Java', 'JVM', 'Java Agent Development Framework']);
SELECT split_platform('Java based DEVS + GRASS', ARRAY['Java', 'JVM', 'GRASS']);
SELECT split_platform('Java, Mason, Netlogo', ARRAY['Java', 'JVM', 'MASON', 'NetLogo']);
SELECT split_platform('JAVA using NetBean IDE with RePast', ARRAY['Java', 'JVM', 'NetBeans', 'Repast']);
SELECT split_platform('Java™ using NetBeans IDE', ARRAY['Java', 'JVM', 'NetBeans', 'Repast']);
SELECT split_platform('JScheme', ARRAY['JScheme', 'JVM']);
SELECT split_platform('matSim(Java)', ARRAY['Java', 'JVM', 'MATSim']);
SELECT split_platform('MS Excel with Visual Basic for Applications (VBA)', ARRAY['MS Excel', 'MS VBA (Visual Basic for Applications)']);
SELECT split_platform('Netlogo and C language', ARRAY['NetLogo', 'C']);
SELECT split_platform('Netlogo, Visual Basic', ARRAY['NetLogo', 'MS VB (Visual Basic)']);
SELECT split_platform('Repast Simphony + open source GIS software from JTS', ARRAY['Repast', 'JTS']);
SELECT split_platform('RepastPy', ARRAY['Repast', 'Python']);
SELECT split_platform('SLAPP-python', ARRAY['SLAPP', 'Python']);
SELECT split_platform('Virtual Laboratory Environment (VLE)', ARRAY['VLE (Virtual Laboratory Environment']);
SELECT split_platform('Visual C++/CLI', ARRAY['MS Visual C++', 'MS Visual Studio']);
SELECT split_platform('Visual Studio C++', ARRAY['MS Visual C++', 'MS Visual Studio']);
SELECT split_platform('Windows XP Server with SQL Server and Internet Information Server', ARRAY['MS SQL Server', 'IIS (Internet Information Server)']);

SELECT merge_platform(ARRAY['AcrGIS', 'ArcGIS', 'ESRI ArcGIS'], 'ArcGIS');
SELECT merge_platform(ARRAY['AnyLogic', 'Anylogic'], 'AnyLogic');
SELECT merge_platform(ARRAY['Borland''s Delphi', 'Delphi', 'Delphi 4', 'Delphi (Object Pascal)'], 'Delphi');
SELECT merge_platform(ARRAY['C#', 'C#.NET', '.NET'], '.NET');
SELECT merge_platform(ARRAY['Eclipse', 'Eclipse IDE', 'Eclipse SDK'], 'Eclipse');
SELECT merge_platform(ARRAY['Fortran95', 'FORTRAN', 'FORTRAN 90'], 'Fortran');
SELECT merge_platform(ARRAY[
  'JADE',
  'JADE (Java Agent Development Environment)',
  'JADE – Java Agent Development Framework,'], 'JADE (Java Agent Development Environment)');
SELECT merge_platform(ARRAY['JavaScript', 'Javascript'], 'JavaScript');
SELECT merge_platform(ARRAY[
    'LEADSTO',
    'LEADSTO language and simulation environment'], 'LEADSTO');
SELECT merge_platform(ARRAY['MatLab', 'Matlab'], 'MatLab');
SELECT merge_platform(ARRAY['Microsoft Excel', 'MS Excel'], 'MS Excel');
SELECT merge_platform(ARRAY['Microsoft Visual Studio', 'MS Visual Studio'], 'MS Visual Studio');
SELECT merge_platform(ARRAY['Microsoft XNA'], 'MS XNA');
SELECt merge_platform(ARRAY['Mp-mas', 'MP-MAS'], 'MP-MAS');
SELECT merge_platform(ARRAY['Netlogo', 'Netlogo 4.1', 'Netlogo 4.1.2', 'NetLogo'], 'NetLogo');
SELECT merge_platform(ARRAY[
    'PHP',
    'PHP 5'], 'PHP');
SELECT merge_platform(ARRAY['Python', 'Pyton'], 'Python');
SELECT merge_platform(ARRAY[
    'RepastJ',
    'Repast J 3.1',
    'Repast',
    'Repast 2.0',
    'Repast Simphony',
    'Repast Simphony 2.0'], 'Repast');
SELECT merge_platform(ARRAY['Visual Basic', 'VB (Visual Basic)', 'MS VB (Visual Basic)'], 'MS VB (Visual Basic)');

DELETE FROM core_publication_platforms
  WHERE platform_id =
        (SELECT id
        FROM core_platform
        WHERE "name" = ANY(ARRAY['None', 'Unknown', 'unknown', '']));

DELETE FROM core_platform
WHERE "name" = ANY(ARRAY['None', 'Unknown', 'unknown', '']);

CREATE OR REPLACE FUNCTION split_sponsor(_val TEXT, _new_vals TEXT[]) RETURNS VOID AS
  $$
    DECLARE
      _publication_ids INT[];
      _publication_id INT;
      _sponsor_id INT;
      _new_sponsor_id INT;
      _new_val TEXT;
    BEGIN
      SELECT id
      INTO _sponsor_id
      FROM core_sponsor
      WHERE name = _val;

      SELECT array_agg(publication_id)
      INTO _publication_ids
      FROM core_publication_sponsors
      WHERE sponsor_id = _sponsor_id;

      RAISE NOTICE 'sponsor_id: %', _sponsor_id;
      RAISE NOTICE 'publication_ids: %', array_to_string(_publication_ids, ',', 'NULL');

      RAISE NOTICE 'deleting old core_sponsor %', _sponsor_id;

      DELETE FROM core_publication_sponsors
      WHERE sponsor_id = _sponsor_id OR sponsor_id IN
        (SELECT id FROM core_sponsor WHERE "name" = ANY(_new_vals));

      DELETE FROM core_sponsor
      WHERE id = _sponsor_id OR "name" = ANY(_new_vals);

      FOREACH _new_val IN ARRAY _new_vals
      LOOP
        SELECT nextval('core_sponsor_id_seq') INTO _new_sponsor_id;

        RAISE NOTICE 'inserted %, % into core_platform', _new_sponsor_id, _new_val;
        INSERT INTO core_sponsor (id, "name") VALUES (_new_sponsor_id, _new_val);

        INSERT INTO core_publication_sponsors (publication_id, sponsor_id)
        SELECT unnest(_publication_ids), _new_sponsor_id;
      END LOOP;
    END;
  $$ LANGUAGE plpgsql VOLATILE;

CREATE OR REPLACE FUNCTION merge_sponsor(_sponsor_names TEXT[], _sponsor_name TEXT) RETURNS VOID AS
  $$
  DECLARE
    _publication_ids INT[];
    _sponsor_ids INT[];
    _sponsor_id INT;
  BEGIN
    SELECT array_agg(id)
    INTO _sponsor_ids
    FROM core_sponsor
    WHERE "name" = ANY(_sponsor_names);

    SELECT id INTO _sponsor_id FROM core_sponsor WHERE "name" = _sponsor_name;

    SELECT array_agg(DISTINCT publication_id)
    INTO _publication_ids
    FROM core_publication_sponsors
    WHERE sponsor_id = ANY(_sponsor_ids) OR sponsor_id = _sponsor_id;

    RAISE NOTICE '_sponsor_names: %', array_to_string(_sponsor_names, ',', 'NULL');
    RAISE NOTICE '_sponsor_ids: %', array_to_string(_sponsor_ids, ',', 'NULL');
    RAISE NOTICE '_sponsor_id: %', _sponsor_id;

    DELETE FROM core_publication_sponsors
    WHERE sponsor_id = ANY(_sponsor_ids) OR sponsor_id = _sponsor_id;

    DELETE FROM core_sponsor
    WHERE id = ANY(_sponsor_ids) OR id = _sponsor_id;

    SELECT nextval('core_sponsor_id_seq') INTO _sponsor_id;
    INSERT INTO core_sponsor (id, name) VALUES (_sponsor_id, _sponsor_name);

    INSERT INTO core_publication_sponsors (publication_id, sponsor_id)
    SELECT unnest(_publication_ids), _sponsor_id;
  END;
  $$ LANGUAGE plpgsql VOLATILE;

SELECT split_sponsor(
  'Department of Political Science and Center for the Advanced Study of International Development at Michigan State University',
  ARRAY[
  'Department of Political Science and Center at Michegan State University',
  'Center for the Advanced Study of International Development at Michegan State University'
  ]
);
SELECT split_sponsor(
  'Deutscher Akademischer Austauschdienst and the Landesbank Schleswig-Holstein',
  ARRAY[
  'Deutscher Akademischer Austauschdienst',
  'Landesbank Schleswig-Holstein'
  ]
);
SELECT split_sponsor(
  'Directorate General for Research of the Government of Catalonia (2009SGR-1492) and from the Ministry of Science and Innovation of the Spanish Government',
  ARRAY[
  'Directorate General for Research of the Government of Catalonia',
  'Ministry of Science and Innovation of the Spanish Government'
  ]
);
SELECT split_sponsor(
  'EPSRC/BBSRC',
  ARRAY[
  'United Kingdom Engineering and Physical Sciences Research Council (EPSRC)',
  'United Kingdom Biotechnology and Biological Sciences Research Council (BBSRC)'
  ]
);
SELECT split_sponsor(
  'ESRC/NERC',
  ARRAY[
  'United Kingdom Economic and Social Research Council (ESRC)',
  'United Kingdom Natural Environment Research Council (NERC)'
  ]
);
SELECT split_sponsor(
  'FEDER/POCTI',
  ARRAY[
  'European Regional Development Fund (ERDF/FEDER)'
  'Portugal Science, Technology, Innovation Operational Programme'
  ]
);
SELECT split_sponsor(
  'Graham Environmental Sustainability Institute and the Rackham Graduate School at University of Michigan',
  ARRAY[
  'Graham Environmental Sustainability Institute at University of Michigan (GESI)',
  'Rackham Graduate School at University of Michigan'
  ]
);
SELECT split_sponsor(
  'National Natural Science Foundation of China, National Social Science Foundation of China',
  ARRAY[
    'National Natural Science Foundation of China',
    'National Social Science Foundation of China'
  ]
);
SELECT split_sponsor(
  'UK ESRC/NERC Interdisciplinary Studentship',
  ARRAY[
  'United Kingdom Economic and Social Research Council (ESRC)',
  'United Kingdom Natural Environment Research Council (NERC)'
  ]
);


SELECT merge_sponsor(
  ARRAY[
    'Air Force Office of Scientific Research',
    'Air Force Office of Sponsored Research',
    'Air Force Research Laboratories Human Effectiveness Directorate',
    'Air Force Research Laboratory'
  ],
  'United States Air Force'
);
SELECT merge_sponsor(
  ARRAY[
  'Australian Research Council',
  'Australian Research Council (ARC)',
  'Australian Research Council Australian Research Fellowship',
  'Australian Research Council Discovery',
  'Australian Research Council–New Zealand Vegetation Function Network',
  'Australian Research Council’s Discovery Project',
  'Australian Research Countil'
  ],
  'Australian Research Council (ARC)'
);

SELECT merge_sponsor(
  ARRAY[
    'Bill and Melinda Gates Foundation',
    'Bill & Melinda Gates Foundation'
  ],
  'Bill & Melinda Gates Foundation'
);
SELECT merge_sponsor(
  ARRAY[
  'Canadian Institutes for Health Research',
  'Canadian Institutes of Health Research'
  ],
  'Canadian Institutes for Health Research'
);
SELECT merge_sponsor(
  ARRAY[
  'Center for Social Complexity at George Mason University',
  'Center for Social Complexity of George Mason University'
  ],
  'Center for Social Complexity at George Mason University'
);
SELECT merge_sponsor(
  ARRAY[
    'Centre National de la Recherche Scientifique',
    'Centre National de la Recherche Scientifique (CNRS)',
    'Unité Mixte de Recherche (UMR) 5558'
  ],
  'Centre National de la Recherche Scientifique (CNRS)'
);
SELECT merge_sponsor(
    ARRAY[
      'CSIRO',
      'CSIRO flagship Water for a Healthy Country',
      'CSIRO Water for a Healthy Country',
      'Commonwealth Scientific and Industrial Research Organisation (CSIRO)'
    ],
    'Commonwealth Scientific and Industrial Research Organisation (CSIRO)'
);
SELECT merge_sponsor(
  ARRAY[
    'CNCSIS -UEFISCSU',
    'CNCSIS–UEFISCSU'
  ],
  'Romanian National Council of Scientific Research (Consiliul National al Cercetarii Stiintifice din Invatamantul Superior CNCSIS)'
);
SELECT merge_sponsor(
  ARRAY[
  'Brazilian Research CNPq',
  'CNPq',
  'Conselho Nacional de Desenvolvimento Cientí¯co e Tecnologico',
  'Conselho Nacional de Desenvolvimento Científico e Tecnológico',
  'Conselho Nacional de Desenvolvimento Científico e Tecnológico (CNPq)'
  ],
  'Brazilian National Council for Scientific and Technological Development (CNPq)'
);
SELECT merge_sponsor(
  ARRAY[
  'Danish Natural Science Research Council',
  'Danish Natural Sciences Research Council'
  ],
  'Danish Natural Science Research Council'
);
SELECT merge_sponsor(
  ARRAY[
  'DARPA',
  'Defense Advanced Research Planning Agency'
  ],
  'United States Defense Advanced Research Planning Agency (DARPA)'
);
SELECT merge_sponsor(
  ARRAY[
  'Department of Education',
  'department of education'
  ],
  'United States Department of Education'
);
SELECT merge_sponsor(
  ARRAY[
  'Department of Radiology at Massachusetts General Hospital',
  'Department of Radiology at Massachusetts General Hospital.'
  ],
  'Department of Radiology at Massachusetts General Hospital'
);
SELECT merge_sponsor(
  ARRAY[
  'Deutsche Forschungsgemeinschaft',
  'Deutsche Forschungsgemeinschaft (DFG)',
  'German Research Foundation',
  'German Research Foundation (Deutsche Forschungsgemeinschaft, DFG)'
  ],
  'German Research Foundation (Deutsche Forschungsgemeinschaft, DFG)'
);
SELECT merge_sponsor(
  ARRAY[
  'Deutscher Akademischer Austauschdienst'
  'Deutscher Akademischer Austausch Dienst',
  'Deutscher Akademischer Austauschdienst'
  ],
  'Deutscher Akademischer Austauschdienst'
);
SELECT merge_sponsor(
  ARRAY[
  'Direc- torate General for Research of the Government of Catalonia',
  'Directorate General for Research of the Government of Catalonia'
  ],
  'Directorate General for Research of the Government of Catalonia'
);
SELECT merge_sponsor(
  ARRAY[
    'Economic and Social Research Council',
    'ESRC',
    'UK Economic and Social Research Council at the School of Geography',
    'United Kingdom Economic and Social Research Council (ESRC)'
  ],
  'United Kingdom Economic and Social Research Council (ESRC)'
);
SELECT merge_sponsor(
  ARRAY[
    'Engineering and Physical Sciences Research Council',
    'Engineering and Physical Sciences Research Council (EPSRC)',
    'Engineering and Physical Siences Research Council United Kingdom',
    'EPSRC',
    'UK Engineering and Physical Sciences Research Council',
    'United Kingdom Engineering and Physical Sciences Research Council (EPSRC)'
  ],
  'United Kingdom Engineering and Physical Sciences Research Council (EPSRC)'
);
SELECT merge_sponsor(
  ARRAY[
    'European Commission',
    'European Community',
    'European Community''s Human Potential Programs',
    'European Community Seventh Framework Programme',
    'European Community’s Human Potential Programme',
    'European Community’s Human Potential Programs',
    'European Community’s Seventh Framework Programme',
    'European Community’s Sixth Framework Programme',
    '“Information Society Technology” Programme of the Commission of the European Union',
    'European Union',
    'European Union 7th Framework Programme',
    'European Union''s FEDER program'
  ],
  'European Commission'
);
SELECT merge_sponsor(
  ARRAY[
  'BMBF',
  'BMBF (Federal Ministry of Education and Research)',
  'Federal Ministry of Education and Research (BMBF), Germany',
  'Federal Ministry of Education and Research of the Federal Republic of Germany',
  'German Federal Ministry for Education and Research (BMBF)',
  'German Federal Ministry of Education and Research',
  'German Federal Ministry of Education and Research (BMBF)',
  'German Ministry of Education and Research',
  'German Ministryof Education and Research in the framework of BIOTA Southern Africa'
  ],
  'German Federal Ministry of Education and Research (BMBF)'
);
SELECT merge_sponsor(
  ARRAY[
    'German Research Foundation (Deutsche Forschungsgemeinschaft, DFG)',
    'German Research Foundation (DFG)',
    'Deutsches Forschungsgemeinschaft (DFG)'
  ],
  'German Research Foundation (Deutsche Forschungsgemeinschaft, DFG)'
);
SELECT merge_sponsor(
  ARRAY[
  'FEDER (EU)'
  ],
  'European Regional Development Fund (ERDF/FEDER)'
);
SELECT merge_sponsor(
  ARRAY[
  'Fondecyt',
  'FONDECYT'
  ],
  'Chile National Fund for Scientific and Technological Development (FONDECYT)'
);
SELECT merge_sponsor(
  ARRAY[
  'Fundação de Amparo à Pesquisa do Estado da Bahia',
  'Fundação de Amparo à Pesquisa do Estado da Bahia (FAPESB)'
  ],
  'Fundação de Amparo à Pesquisa do Estado da Bahia (FAPESB)'
);
SELECT merge_sponsor(
  ARRAY[
  'French Research Ministry',
  'French Research Ministry (EGIDE)'
  ],
  'French Research Ministry (EGIDE)'
);
SELECT merge_sponsor(
  ARRAY[
    'Fundação para a Ciência e a Tecnologia',
    'Fundacao para a Ciencia e a Tecnologia-FCT',
    'Fundacao para a Ciencia e a Tecnologia under Bolsa de Investigacao',
    'Foundation for Science and Technology of Portugal',
    'Portugal Foundation for Science and Technology',
    'Portugal Foundation for Science and Technology (FCT)',
    'Portuguese Foundation for Science and Technology (FCT)'
  ],
  'Portuguese Foundation for Science and Technology (FCT)'
);
SELECT merge_sponsor(
  ARRAY[
  'Fundamental Research Funds for the Central Universities',
  'Fundamental Research Funds for the Central Universities of China'
  ],
  'Fundamental Research Funds for the Central Universities of China'
);
SELECT merge_sponsor(
  ARRAY[
    'Graham Environmental Sustainability Institute (GESI) at the University of Michigan',
    'Graham Environmental Sustainability Institute at University of Michigan (GESI)'
  ],
  'Graham Environmental Sustainability Institute at University of Michigan (GESI)'
);
SELECT merge_sponsor(
  ARRAY[
    'Human Frontier Science Program',
    'Human Frontiers Science Program'
  ],
  'Human Frontier Science Program'
);
SELECT merge_sponsor(
  ARRAY[
    'Institute for Critical Technologies and Applied Science',
    'Institute for Critical Technology and Applied Science at Virginia Tech'
  ],
  'Institute for Critical Technology and Applied Science at Virginia Tech'
);
SELECT merge_sponsor(
  ARRAY[
    'International Rice Research Institute',
    'International Rice Research Institute (IRRI)'
  ],
  'International Rice Research Institute (IRRI)'
);
SELECT merge_sponsor(
  ARRAY[
    'Israeli National Science Foundation',
    'Israeli Science Foundation',
    'Israel Science Foundation'
  ],
  'Israeli National Science Foundation'
);
SELECT merge_sponsor(
  ARRAY[
    'Italian Minister of University and Scientific Research',
    'Italian Ministry for the University and the Scientific Research',
    'Italian Ministry of University and Research',
    'Italian MIUR FISR Project',
    'Italian National Ministry of University and Scientific Research'
  ],
  'Italian Ministry for University and Scientific Research'
);
SELECT merge_sponsor(
  ARRAY[
    'IWT',
    'IWT (Flemish Fund for Applied Science)'
  ],
  'Flemish Innovation by Science anf Technology (IWT)'
);
SELECT merge_sponsor(
  ARRAY[
    'James C. McDonnell Foundation',
    'James S. McDonnell Foundation'
  ],
  'James S. McDonnell Foundation'
);
SELECT merge_sponsor(
  ARRAY[
    'Japan Society for the Promotion of Science',
    'Japan Society for the Promotion of Science for Young Scientists',
    'JSPS'
  ],
  'Japan Society for the Promotion of Science (JSPS)'
);
SELECT merge_sponsor(
  ARRAY[
    'Korea government',
    'Korean Government'
  ],
  'Korean Government'
);
SELECT merge_sponsor(
  ARRAY[
    'Leverhulme Foundation',
    'Leverhulme Trust'
  ],
  'Leverhulme Trust'
);
SELECT merge_sponsor(
  ARRAY[
    'Lilly Endowment',
    'Lilly Endowment grant'
  ],
  'Lilly Endowment'
);
SELECT merge_sponsor(
  ARRAY[
    'Marie Curie Integration grant (ITN)',
    'Marie Curie International Fellowship',
    'Marie Curie Programme'
  ],
  'Marie Curie'
);
SELECT merge_sponsor(
  ARRAY[
    'MCyT',
    'MCyT (Spain)'
  ],
  'MCyT (Spain)'
);
SELECT merge_sponsor(
  ARRAY[
    'NASA',
    'NASA Specialized Center of Research',
    'US National Aeronautics and Space Administration (NASA)'
  ],
  'United States National Aeronautics and Space Administration (NASA)'
);
SELECT merge_sponsor(
  ARRAY[
    'National Cancer Institute',
    'National Cancer Institute (NCI)'
  ],
  'National Cancer Institute (NCI)'
);
SELECT merge_sponsor(
  ARRAY[
    'National Health and Medical Research Council',
    'NHMRC',
    'NHMRC Principal Research Fellowship',
    'National Health and Medical Research Council (NHMRC)'
  ],
  'Australian National Health and Medical Research Council (NHMRC)'
);
SELECT merge_sponsor(
  ARRAY[
    'National Institute of Allergy and Infectious Diseases',
    'National Institute Of Allergy And Infectious Diseases'
  ],
  'National Institute Of Allergy And Infectious Diseases'
);
SELECT merge_sponsor(
  ARRAY[
    'National institutes of health',
    'National Institutes of Health',
    'National Institutes of Health/National Institute of General Medical Sciences',
    'National Institutes of Health (NIH)',
    'National Institutes of Health Ruth L. Kirschstein National Research Service Award',
    'NIH',
    'NIH Award',
    'NIH career development',
    'NIH Grant',
    'NIH Models of Infectious Disease Agent Study (MIDAS)',
    'NIH, National, Lung and Blood Institute and Office of Behavioral and Social Sciences Research',
    'NIH/NIDA grant DA 10736',
    'NIH/NLM',
    'US National Institutes of Health'
  ],
  'United States National Institutes of Health (NIH)'
);
SELECT merge_sponsor(
  ARRAY[
    'NOAA',
    'NOAA Oceans and Human Health Initiative',
    'Oceans and Human Health Initiative (OHHI) of NOAA'
  ],
  'Oceans and Human Health Initiative (NOAA)'
);
SELECT merge_sponsor(
  ARRAY[
    'National Research Council',
    'National Research Council of Canada (NRC)'
  ],
  'National Research Council of Canada (NRC)'
);
SELECT merge_sponsor(
  ARRAY[
    'National Research Foundation of Korea',
    'National Research Foundation of Korea (NRF)'
  ],
  'National Research Foundation of Korea (NRF)'
);
SELECT merge_sponsor(
  ARRAY[
    'National Science Council in Taiwan',
    'National Science Council of Taiwan',
    'National Science Council Taiwan'
  ],
  'National Science Council of Taiwan'
);
SELECT merge_sponsor(
  ARRAY[
    'National Science Foundation China',
    'National Science Foundation of China'
  ],
  'National Science Foundation of China'
);
SELECT merge_sponsor(
  ARRAY[
    'Natural Environment Research Council',
    'Natural Environment Research Council (NERC)',
    'NERC',
    'NERC studentship',
    'United Kingdom Natural Environment Research Council (NERC)'
  ],
  'United Kingdom Natural Environment Research Council (NERC)'
);
SELECT merge_sponsor(
  ARRAY[
    'National Institute of Dental and Craniofacial Research',
    'National Institute of Dental & Craniofacial Research'
  ],
  'National Institute of Dental & Craniofacial Research'
);
SELECT merge_sponsor(
  ARRAY[
    'National Institute of General Medical Sciences',
    'National Institute of General Medical Sciences Models of Infectious Disease Agent Study (MIDAS)'
  ],
  'National Institute of General Medical Sciences'
);
SELECT merge_sponsor(
  ARRAY[
    'national Key Technology R&D Program',
    'National Key Technology R&D Program of China'
  ],
  'National Key Technology R&D Program of China'
);
SELECT merge_sponsor(
  ARRAY[
    'Natural Sciences and Engineering Council of Canada',
    'Natural Sciences and Engineering Council of Canada (NSERC) Strategic Grants program',
    'Natural Sciences and Engineering Research Council',
    'Natural Sciences and Engineering Research Council (NSERC) of Canada',
    'Natural Sciences and Engineering Research Council of Canada',
    'Natural Sciences and Engineering Research Council of Canada (CAAB)',
    'Natural Sciences and Engineering Research Council of Canada (NSERC)',
    'NSERC',
    'NSERC Canada'
  ],
  'Natural Sciences and Engineering Research Council of Canada (NSERC)'
);
SELECT merge_sponsor(
  ARRAY[
    'Netherlands Organisation for Scientific Research',
    'Netherlands Organisation for Scientific Research (NWO)',
    'Netherlands Organization for Scientific Research',
    'Netherlands Organization for Scientific Research (NWO)'
  ],
 'Netherlands Organization for Scientific Research (NWO)'
);
SELECT merge_sponsor(
  ARRAY[
    'Ofce of Naval Research',
    'Office of Naval Research'
  ],
  'Office of Naval Research'
);
SELECT merge_sponsor(
  ARRAY[
    'Oxford Kobe scholarship',
    'Oxford University'
  ],
  'University of Oxford'
);
SELECT merge_sponsor(
  ARRAY[
    'Program for New Century Excellent Talents in University',
    'Program for New Century Excellent Talents in University China'
  ],
  'Chinese Program for New Century Excellent Talents in University'
);
SELECT merge_sponsor(
  ARRAY[
    'Public Health Service',
    'Public Health Services'
  ],
  'United States Public Health Service'
);
SELECT merge_sponsor(
  ARRAY[
    'Research Foundation - Flanders',
    'Research Foundation–Flanders'
  ],
  'Flanders Research Foundation'
);
SELECT merge_sponsor(
  ARRAY[
    'Research Grants Council of Hong Kong',
    'Research Grants Council of the Hong Kong',
    'Research Grants Council of the Hong Kong SAR',
    'Research Grants Council of the Hong Kong Special Administrative Region'
  ],
  'Research Grants Council of Hong Kong'
);
SELECT merge_sponsor(
  ARRAY[
    'Sandia Corporation',
    'Sandia National Laboratories (SNL)',
    'Lockheed Martin'
  ],
  'Lockheed Martin'
);
SELECT merge_sponsor(
  ARRAY[
    'Santa Fe Inst.',
    'Santa Fe Institute'
  ],
  'Santa Fe Institute'
);
SELECT merge_sponsor(
  ARRAY[
  'Scottish Government Rural and Environment Research and Analysis Directorate (RERAD)',
  'Scottish Government Rural and Environment Research and Analysis Directorate'
  ],
  'RERAD (Scottish Government Rural and Environment Research and Analysis Directorate)'
);
SELECT merge_sponsor(
  ARRAY[
    'SEP-CONACYT',
    'CONACYT',
    'CONACyT (México)',
    'El Fondo Sectorial de Investigación para la Educación (SEP-CONACYT)'
  ],
  'El Fondo Sectorial de Investigación para la Educación (SEP-CONACYT)'
);
SELECT merge_sponsor(
  ARRAY[
    'Social Science and Humanities Research Council of Canada (SSHRC)',
    'Social Sciences and Humanities Research Council',
    'Social Sciences and Humanities Research Council of Canada',
    'Social Sciences and Humanities Research Council (SSHRC) of Canada'
  ],
  'Social Science and Humanities Research Council of Canada (SSHRC)'
);
SELECT merge_sponsor(
  ARRAY[
    'Swedish Foundation for Strategic Research',
    'Swedish Foundation for Strategic Research (PH)'
  ],
  'Swedish Foundation for Strategic Research (PH)'
);
SELECT merge_sponsor(
  ARRAY[
    'Swedish Research Council',
    'Swedish Research Council (PH)'
  ],
  'Swedish Research Council (PH)'
);
SELECT merge_sponsor(
  ARRAY[
    'Swiss National Science Foundation',
    'Swiss National Science Foundation Grant'
  ],
  'Swiss National Science Foundation'
);
SELECT merge_sponsor(
  ARRAY[
    'The Center for Advanced Study of International Development at Michigan State University',
    'Center for Advanced Study of International Development at Michigan State University'
  ],
  'Center for Advanced Study of International Development at Michigan State University'
);
SELECT merge_sponsor(
  ARRAY[
    'The University of Tennessee',
    'University of Tennessee'
  ],
  'University of Tennessee'
);
SELECT merge_sponsor(
  ARRAY[
    'Turkish Academy of Sciences',
    'Turkish Academy of Sciences (TUBA)'
  ],
  'Turkish Academy of Sciences (TUBA)'
);
SELECT merge_sponsor(
  ARRAY[
    'Toyota Central R&D Labs',
    'Toyota Central R&D Labs.'
  ],
  'Toyota'
);
SELECT merge_sponsor(
  ARRAY[
    'UK DEFRA'
  ],
  'United Kingdom Department for Environment, Food & Rural Affairs'
);
SELECT merge_sponsor(
  ARRAY[
    'UK Research Council'
  ],
  'United Kingdom Research Council'
);
SELECT merge_sponsor(
  ARRAY[
    'United Kingdom’s Department for International Development'
  ],
  'United Kingdom Department for International Development'
);
SELECT merge_sponsor(
  ARRAY[
    'U.S. Army',
    'US Army',
    'US Army Engineer District Walla Walla',
    'U.S. Army Research',
    'U.S. Army Research Laboratory',
    'US Army Research Office'
  ],
  'United States Army'
);
SELECT merge_sponsor(
  ARRAY[
    'USDA',
    'USDA IFAFS',
    'USDA’s Program of Research on the Economics of Invasive Species Management',
    'U.S. Department of Agriculture',
    'US Department of Agriculture',
    'U.S. Department of Agriculture (USDA)'
  ],
  'United States Department of Agriculture (USDA)'
);
SELECT merge_sponsor(
  ARRAY[
    'US Department of Defense'
  ],
  'United States Department of Defense'
);
SELECT merge_sponsor(
  ARRAY[
    'US Department of Education',
    'United States Department of Education'
  ],
  'United States Department of Education'
);
SELECT merge_sponsor(
  ARRAY[
    'US Department of Energy',
    'US Department of Energy’s National Nuclear Security Administration',
    'U.S. DOE',
    'department of energy',
    'Department of Energy',
    'United States Department of Energy'
  ],
  'United States Department of Energy (DOE)'
);
SELECT merge_sponsor(
  ARRAY[
    'US Department of Health and Human Services'
  ],
  'United States Department of Health and Human Services'
);
SELECT merge_sponsor(
  ARRAY[
    'U.S. Department of Homeland Security',
    'US Department of Homeland Security',
    'U.S. Department of Homeland Security Science & Technology Directorate'
  ],
  'United States Department of Homeland Security'
);
SELECT merge_sponsor(
  ARRAY[
    'US Department of the Interior'
  ],
  'United States Department of the Interior'
);
SELECT merge_sponsor(
  ARRAY[
    'US Department of Veterans Affairs Medical Informatics',
    'Veterans Affairs Office of Research and Development'
  ],
  'United States Department of Veterans Affairs'
);
SELECT merge_sponsor(
  ARRAY[
    'U.S. Environmental Protection Agency',
    'US Environmental Protection Agency Science to Achieve Results (STAR)'
  ],
  'United States Environmental Protection Agency'
);
SELECT merge_sponsor(
  ARRAY[
    'U.S. Geological Survey (USGS)'
  ],
  'United States Geological Survey (USGS)'
);
SELECT merge_sponsor(
  ARRAY[
    'U.S Marine Mammal Commission'
  ],
  'United States Marine Mammal Commission'
);
SELECT merge_sponsor(
  ARRAY[
    'US National Fire Plan'
  ],
  'United States National Fire Plan'
);
SELECT merge_sponsor(
  ARRAY[
    'National Science Council', -- All authors are from Taiwan so I assumed it was not funded by the PRC version
    'National Science Council of Taiwan'
  ],
  'National Science Council of Taiwan'
);
SELECT merge_sponsor(
  ARRAY[
    'National Science Foundation',
    'National Science Foundation Award',
    'National Science Foundation Biocomplexity in the Environment Programme',
    'National Science Foundation Graduate Research Fellowship',
    'National Science Foundation Grant 0921904 (to ML)',
    'NSF',
    'NSF Graduate Research Fellowship',
    'NSF Grant',
    'NSF Virgin Islands Experimental Program to Stimulate Competitive Research',
    'U.S. National Science Foundation',
    'U.S. NationalScience Foundation',
    'US National Science Foundation',
    'US National Science Foundation Directorate for Social'
  ],
  'United States National Science Foundation (NSF)'
);
SELECT merge_sponsor(
  ARRAY[
    'VEGA grants',
    'VEGA (Scientific Grant Agency)'
  ],
  'VEGA (Scientific Grant Agency)'
);
SELECT merge_sponsor(
  ARRAY[
    'Volkswagen Foundation',
    'Volkswagenstiftung'
  ],
  'Volkswagen Foundation (Volkswagenstiftung)'
);
SELECT merge_sponsor(
  ARRAY[
    'Wallonia Brussels International',
    'Wallonia-Brussels International'
  ],
  'Wallonia-Brussels International'
);
SELECT merge_sponsor(
  ARRAY[
    'Wenner-Gren Foundation for Anthropological Research',
    'Wenner-Gren foundations',
    'Wenner-Gren Foundations (SM)'
  ],
  'Wenner-Gren Foundations (SM)'
);
SELECT merge_sponsor(
  ARRAY[
    'Whitaker Foundation',
    'Whitaker Foundation, Arlington, VA',
    'Whitaker International Programme'
  ],
  'Whitaker Foundation'
);

DELETE FROM core_publication_sponsors
  WHERE sponsor_id IN (
      SELECT id
      FROM core_sponsor
      WHERE lower(name) IN ('none', 'unclear', 'unknown', 'phd grant', 'www.ivv.tuwien.ac.at/forschung/mars-metropolitan-activity-relocation-simulator.html')
  );

DELETE FROM core_sponsor
WHERE lower(name) in ('none', 'unclear', 'unknown', 'phd grant', 'www.ivv.tuwien.ac.at/forschung/mars-metropolitan-activity-relocation-simulator.html');
COMMIT;

-- After Check
-- COPY
-- (SELECT c_pub.id, max(title) AS title, array_agg(DISTINCT c_plat.name ORDER BY c_plat.name) AS platforms, array_agg(DISTINCT c_spons.name ORDER BY c_spons.name) AS sponsors
-- FROM core_publication AS c_pub
--   LEFT JOIN core_publication_platforms AS c_pub_plat ON c_pub.id = c_pub_plat.publication_id
--   LEFT JOIN core_platform AS c_plat ON c_pub_plat.platform_id = c_plat.id
--   LEFT JOIN core_publication_sponsors AS c_pub_spons ON c_pub.id = c_pub_spons.publication_id
--   LEFT JOIN core_sponsor AS c_spons ON c_pub_spons.sponsor_id = c_spons.id
-- GROUP BY c_pub.id)
-- TO '/home/ubuntu/postgres/new_publication_summary.csv'
-- WITH (FORMAT csv, HEADER TRUE, DELIMITER ',');