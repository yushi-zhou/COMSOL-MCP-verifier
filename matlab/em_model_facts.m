function facts = em_model_facts(model, topics)
%EM_MODEL_FACTS Read bounded semantic facts from the currently loaded model.
% No geometry build, mesh build, solve, result evaluation, or model mutation.
% Failed/unsupported reads are explicit issues, never guessed defaults.
allowed = {'studies','physics','excitation','periodic','materials','selections','mesh','outputs'};
if nargin < 2 || isempty(topics); topics = allowed; end
topics = strings_list(topics);
if any(~ismember(topics, allowed)); error('em:inspection_topic', 'Unknown model inspection topic.'); end
issues = {};
facts = struct('schema_version', 'em_model_facts_v1', 'topics', {topics});
for k = 1:numel(topics); facts.(topics{k}) = {}; end

if requested('studies')
    studies = {}; solutions = {}; datasets = {};
    names = read_tags(@() model.study.tags, 'studies');
    for k = 1:numel(names)
        tag = names{k}; node = model.study(tag);
        item = basic(node, tag);
        item.features = {};
        children = read_tags(@() node.feature.tags, ['study/' tag]);
        for j = 1:numel(children)
            ft = children{j}; feature = node.feature(ft);
            f = basic(feature, [tag '/' ft]); f.tag = ft;
            [f.properties, f.evaluated_properties] = properties(feature, ...
                {'activate','disabledphysics','useadvanceddisable','plist','pname','plistarr', ...
                 'punit','tlist','usesol','notsolmethod','notstudy','notstudystep'}, f.id);
            item.features{end+1} = f;
        end
        studies{end+1} = item; %#ok<AGROW>
    end
    names = read_tags(@() model.sol.tags, 'solutions');
    for k = 1:numel(names)
        tag = names{k}; node = model.sol(tag);
        item = struct('tag', tag, 'study', [], 'empty', [], 'label', [], 'type', []);
        item.label = read(@() char(node.label()), ['solution/' tag '/label']);
        item.study = read(@() char(node.study()), ['solution/' tag '/study']);
        item.empty = read(@() logical(node.isEmpty()), ['solution/' tag '/empty']);
        if isequal(item.empty, true)
            item.sample_status = 'empty_solution';
            solutions{end+1} = item; %#ok<AGROW>
            continue
        end
        try
            info = mphsolinfo(model, 'soltag', tag, 'NU', 'on');
            fields = {'study','soltype','size','nummesh','sizesolvals','solpar','solvals', ...
                'paramsweepnames','paramsweepvals','dataset','NUsol'};
            for j = 1:numel(fields)
                field = fields{j};
                if isfield(info, field); item.(field) = plain(info.(field)); end
            end
            if isfield(info, 'soltype'); item.type = char(info.soltype); end
            if isempty(item.study); issue(['solution/' tag '/study'], 'unavailable', 'Solution info did not identify a study.'); end
        catch ME
            issue(['solution/' tag '/info'], 'read_failed', ME.message);
        end
        solutions{end+1} = item; %#ok<AGROW>
    end
    names = read_tags(@() model.result.dataset.tags, 'datasets');
    for k = 1:numel(names)
        tag = names{k}; node = model.result.dataset(tag);
        item = basic(node, ['dataset/' tag]); item.id = tag; item.tag = tag;
        [item.properties, item.evaluated_properties] = properties(node, ...
            {'solution','data','data1','data2','comp','geom','solnum','outersolnum'}, item.id);
        item.solution = []; item.source = []; item.study = [];
        if isfield(item.properties, 'solution'); item.solution = item.properties.solution; end
        if isfield(item.properties, 'data'); item.source = item.properties.data; end
        datasets{end+1} = item; %#ok<AGROW>
    end
    % Resolve single-source derived datasets without assuming a default source.
    for k = 1:numel(datasets)
        [solution, chain] = dataset_solution(datasets, datasets{k}.tag, {});
        datasets{k}.solution = solution;
        datasets{k}.source_chain = chain;
        for j = 1:numel(solutions)
            if ischar(solution) && strcmp(solutions{j}.tag, solution)
                datasets{k}.study = solutions{j}.study;
            end
        end
        if isempty(solution); issue(datasets{k}.id, 'unavailable', 'No unambiguous solution binding.'); end
    end
    facts.studies = struct('studies', {studies}, 'solutions', {solutions}, 'datasets', {datasets});
end

component_topics = {'physics','excitation','periodic','materials','selections','mesh'};
if any(ismember(topics, component_topics))
    components = read_tags(@() model.component.tags, 'components');
    for c = 1:numel(components)
        component = components{c}; co = model.component(component);
        if any(ismember(topics, {'physics','excitation','periodic'}))
            names = read_tags(@() co.physics.tags, [component '/physics']);
            for k = 1:numel(names)
                tag = names{k}; node = co.physics(tag); id = [component '/' tag];
                if requested('physics')
                    item = basic(node, id); item.component = component; item.tag = tag;
                    item.selection = selection(@() node.selection, id);
                    facts.physics{end+1} = item;
                end
                if requested('excitation') || requested('periodic')
                    physics_active = read(@() logical(node.isActive()), [id '/active']);
                    physics_features(node, component, tag, id, physics_active, 0);
                    % Background-field settings are physics properties, not
                    % boundary features. Read the actual property node separately.
                    groups = read_tags(@() node.prop.tags, [id '/property_groups']);
                    if requested('excitation') && any(strcmp(groups, 'BackgroundField'))
                        group = node.prop('BackgroundField');
                        [p, e] = properties(group, {'SolveFor','Eb','Ebg'}, [id '/BackgroundField']);
                        if ~isempty(fieldnames(p))
                            background_active = [];
                            if isfield(p, 'SolveFor') && ischar(p.SolveFor)
                                if strcmp(p.SolveFor, 'fullField')
                                    background_active = false;
                                elseif strcmp(p.SolveFor, 'scatteredField')
                                    background_active = physics_active;
                                end
                            end
                            if isempty(background_active)
                                issue([id '/BackgroundField/effective_active'], 'unavailable', 'Background field activation is not established by SolveFor.');
                            end
                            item = struct('id', [id '/BackgroundField'], 'component', component, ...
                                'physics', tag, 'tag', 'BackgroundField', 'type', 'BackgroundField', ...
                                'label', [], 'active', physics_active, 'effective_active', background_active, ...
                                'selection', struct('status', 'not_applicable'), ...
                                'properties', p, 'evaluated_properties', e);
                            facts.excitation{end+1} = item;
                        end
                    end
                end
            end
        end
        if requested('materials')
            names = read_tags(@() co.material.tags, [component '/materials']);
            for k = 1:numel(names)
                tag = names{k}; node = co.material(tag); id = [component '/' tag];
                item = basic(node, id); item.component = component; item.tag = tag;
                item.selection = selection(@() node.selection, id);
                item.properties = struct(); item.evaluated_properties = struct();
                groups = read_tags(@() node.propertyGroup.tags, [id '/property_groups']);
                for j = 1:numel(groups)
                    gt = groups{j}; key = matlab.lang.makeValidName(gt);
                    [item.properties.(key), item.evaluated_properties.(key)] = properties(node.propertyGroup(gt), ...
                        {'n','ki','epsilonr','relpermittivity','mur','relpermeability','sigma', ...
                         'electricconductivity','thermalconductivity','density','heatcapacity'}, [id '/' gt]);
                end
                facts.materials{end+1} = item;
            end
        end
        if requested('selections')
            names = read_tags(@() co.selection.tags, [component '/selections']);
            for k = 1:numel(names)
                tag = names{k}; node = co.selection(tag); id = [component '/' tag];
                item = basic(node, id); item.component = component; item.tag = tag;
                info = selection(@() co.selection(tag), id);
                fields = fieldnames(info);
                for j = 1:numel(fields); item.(fields{j}) = info.(fields{j}); end
                facts.selections{end+1} = item;
            end
        end
        if requested('mesh')
            names = read_tags(@() co.mesh.tags, [component '/mesh']);
            for k = 1:numel(names)
                tag = names{k}; node = co.mesh(tag); id = [component '/' tag];
                item = struct('id', id, 'component', component, 'tag', tag, 'stats', struct(), 'features', {{}});
                try
                    stats = mphmeshstats(model, tag);
                    fields = {'geomtag','component','isempty','hasproblems','iscomplete','sdim', ...
                        'types','numelem','minquality','meanquality','minvolume','maxvolume','volume'};
                    for j = 1:numel(fields)
                        field = fields{j}; if isfield(stats, field); item.stats.(field) = plain(stats.(field)); end
                    end
                    if isfield(stats, 'numelem')
                        item.stats.numelem_by_type = double(stats.numelem);
                        item.stats.numelem = sum(double(stats.numelem(:)));
                    end
                catch ME
                    issue([id '/stats'], 'read_failed', ME.message);
                end
                children = read_tags(@() node.feature.tags, id);
                for j = 1:numel(children)
                    ft = children{j}; feature = node.feature(ft);
                    f = basic(feature, [id '/' ft]); f.tag = ft;
                    [f.properties, f.evaluated_properties] = properties(feature, ...
                        {'hmax','hmin','hgrad','hcurve','hauto','custom'}, f.id);
                    f.selection = selection(@() feature.selection, f.id);
                    if ischar(f.type) && any(strcmp(f.type, {'CopyFace','CopyEdge','CopyDomain'}))
                        f.source = selection(@() feature.selection('source'), [f.id '/source']);
                        f.destination = selection(@() feature.selection('destination'), [f.id '/destination']);
                    end
                    item.features{end+1} = f;
                end
                facts.mesh{end+1} = item;
            end
        end
    end
end

if requested('outputs')
    names = read_tags(@() model.result.numerical.tags, 'outputs');
    for k = 1:numel(names)
        tag = names{k}; node = model.result.numerical(tag);
        item = basic(node, ['output/' tag]); item.tag = tag;
        item.kind = 'numerical';
        [p, item.evaluated_properties] = properties(node, {'data','expr','unit','table','innerinput','outerinput'}, item.id);
        item.properties = p; item.dataset = []; item.expressions = []; item.units = []; item.table = [];
        if isfield(p,'data'); item.dataset = p.data; end
        if isfield(p,'expr'); item.expressions = p.expr; end
        if isfield(p,'unit'); item.units = p.unit; end
        if isfield(p,'table'); item.table = p.table; end
        if ischar(item.type) && any(strcmp(item.type, {'Global','EvalGlobal'}))
            item.selection = struct('status', 'not_applicable');
        else
            item.selection = selection(@() node.selection, item.id);
        end
        facts.outputs{end+1} = item;
    end
    % Export definitions can reference plots rather than numerical evaluations.
    % Follow only those referenced plot groups, without rendering or traversing
    % unrelated result trees. Keep explicit and inherited datasets distinct.
    output_seen = {};
    names = read_tags(@() model.result.export.tags, 'outputs/exports');
    plot_groups = read_tags(@() model.result.tags, 'outputs/plot_groups');
    for k = 1:numel(names)
        tag = names{k}; node = model.result.export(tag);
        item = output_fact(node, ['output/export/' tag], tag, 'export', [], '');
        item.referenced_outputs = {};
        if isfield(item.properties, 'plotgroup')
            plot_group_tag = item.properties.plotgroup;
            if ischar(plot_group_tag) && any(strcmp(plot_groups, plot_group_tag))
                plot_group_id = ['output/plot/' plot_group_tag];
                item.referenced_outputs = {plot_group_id};
                chosen_plot = '';
                if isfield(item.properties, 'plot'); chosen_plot = item.properties.plot; end
                if ischar(chosen_plot) && ~isempty(chosen_plot) && ~any(strcmp(chosen_plot, {'all','none'}))
                    item.referenced_outputs = {[plot_group_id '/' chosen_plot]};
                end
                facts.outputs{end+1} = item;
                output_plots(model.result(plot_group_tag), plot_group_tag, plot_group_id, 'plot_group', [], '', chosen_plot, 0);
                continue
            else
                issue([item.id '/plotgroup'], 'unavailable', 'Referenced plot group is missing or not explicit.');
            end
        end
        facts.outputs{end+1} = item;
    end
end
facts.issues = issues;

    function yes = requested(topic)
        yes = any(strcmp(topics, topic));
    end

    function issue(path, code, message)
        issues{end+1} = struct('path', path, 'code', code, 'message', char(message));
    end

    function value = read(getter, path)
        value = [];
        try; value = plain(getter()); catch ME; issue(path, 'read_failed', ME.message); end
    end

    function list = read_tags(getter, path)
        list = {};
        try; list = strings_list(getter()); catch ME; issue(path, 'read_failed', ME.message); end
    end

    function item = basic(node, id)
        item = struct('id', id, 'tag', id, 'type', [], 'label', [], 'active', []);
        item.unavailable_fields = struct();
        if ismethod(node, 'getType')
            item.type = read(@() char(node.getType()), [id '/type']);
        else
            item.unavailable_fields.type = 'not_applicable';
        end
        item.label = read(@() char(node.label()), [id '/label']);
        if ismethod(node, 'isActive')
            item.active = read(@() logical(node.isActive()), [id '/active']);
        else
            item.unavailable_fields.active = 'not_applicable';
        end
    end

    function result = selection(getter, id)
        result = struct('dimension', [], 'entities', [], 'count', [], 'geometry', [], 'global', []);
        try
            info = mphgetselection(getter());
            result.dimension = double(info.dimension);
            result.geometry = char(info.geom);
            if isfield(info, 'isGlobal'); result.global = logical(info.isGlobal); end
            if isfield(info, 'named'); result.named = char(info.named); end
            if ~isfield(info, 'entities')
                result.status = 'unavailable';
                issue([id '/selection'], 'unavailable', 'Selection has no resolved geometry entities.');
                return
            end
            if iscell(info.entities)
                % Some mesh features select entities of several dimensions.
                % Keep those groups separate; their numeric IDs are not global.
                result.entities = plain(info.entities);
                result.count = sum(cellfun(@numel, info.entities));
                result.entity_layout = 'one_group_per_dimension';
            else
                result.entities = reshape(double(info.entities), 1, []);
                result.count = numel(result.entities);
            end
        catch ME
            if contains(ME.message, 'Entity has no selection')
                result = struct('status', 'not_applicable', 'reason', 'entity_has_no_selection');
            else
                issue([id '/selection'], 'read_failed', ME.message);
            end
        end
    end

    function [raw, evaluated] = properties(node, wanted, id)
        raw = struct(); evaluated = struct();
        try; available = strings_list(node.properties()); catch ME; issue([id '/properties'], 'read_failed', ME.message); return; end
        numeric_properties = {'E0','Eampl','H0','Hampl','Pin','P0','alpha_inc','alpha1_inc','alpha2_inc', ...
            'kFloquet','kFloquetx','kFloquety','kFloquetz','n','ki','epsilonr','relpermittivity', ...
            'mur','relpermeability','sigma','electricconductivity','thermalconductivity','density', ...
            'heatcapacity','hmax','hmin','hgrad','hcurve'};
        for a = 1:numel(wanted)
            name = wanted{a};
            if ~any(strcmp(available, name)); continue; end
            try
                value = property_value(node, name);
                raw.(name) = value;
                if any(strcmp(numeric_properties, name))
                    evaluated.(name) = configuration_value(value, [id '/' name]);
                end
            catch ME
                issue([id '/' name], 'read_failed', ME.message);
            end
        end
    end

    function output = configuration_value(value, id)
        output = struct('status', 'unavailable', 'value_real', [], 'value_imag', [], 'unit', []);
        if isnumeric(value) || islogical(value)
            output = struct('status','ok','value_real',real(value),'value_imag',imag(value),'unit','1');
            return
        end
        if ischar(value); expressions = {value}; elseif iscell(value); expressions = value; else; return; end
        real_values = cell(size(expressions)); imag_values = cell(size(expressions)); units = cell(size(expressions));
        try
            for b = 1:numel(expressions)
                % mphevaluate reads parameter expressions without a dataset.
                [v, u] = mphevaluate(model, char(expressions{b}));
                if any(~isfinite(v(:))); error('em:inspection_nonfinite', 'Nonfinite parameter expression.'); end
                real_values{b} = real(v); imag_values{b} = imag(v); units{b} = char(u);
            end
            if numel(expressions) == 1
                output = struct('status','ok','value_real',real_values{1},'value_imag',imag_values{1},'unit',units{1});
            else
                output = struct('status','ok','value_real',{real_values},'value_imag',{imag_values},'unit',{units});
            end
        catch ME
            issue([id '/configuration_value'], 'unavailable', ME.message);
        end
    end

    function physics_features(parent, component, physics, prefix, parent_active, depth)
        if depth >= 12; issue(prefix, 'unavailable', 'Feature nesting exceeds inspection depth.'); return; end
        % Distinct local names matter here: MATLAB nested functions otherwise
        % share same-named outer variables, which breaks recursive traversal.
        feature_tags = read_tags(@() parent.feature.tags, [prefix '/features']);
        for feature_index = 1:numel(feature_tags)
            feature_tag = feature_tags{feature_index};
            feature_node = parent.feature(feature_tag); feature_id = [prefix '/' feature_tag];
            feature_kind = read(@() char(feature_node.getType()), [feature_id '/type']);
            feature_active = read(@() logical(feature_node.isActive()), [feature_id '/active']);
            effective_state = [];
            if ~isempty(feature_active) && ~isempty(parent_active); effective_state = feature_active && parent_active; end
            feature_is_periodic = ischar(feature_kind) && contains(lower(feature_kind), 'periodic');
            feature_is_excitation = ischar(feature_kind) && (contains(lower(feature_kind), 'port') || ...
                contains(lower(feature_kind), 'planewave') || contains(lower(feature_kind), 'scattering') || ...
                contains(lower(feature_kind), 'diffraction') || contains(lower(feature_kind), 'polarization'));
            if (requested('periodic') && feature_is_periodic) || (requested('excitation') && feature_is_excitation)
                fact_row = basic(feature_node, feature_id); fact_row.tag = feature_tag;
                fact_row.component = component; fact_row.physics = physics;
                fact_row.effective_active = effective_state;
                fact_row.selection = selection(@() feature_node.selection, feature_id);
                [fact_row.properties, fact_row.evaluated_properties] = properties(feature_node, ...
                    {'PortType','PortExcitation','PortName','InputType','E0','Eampl','H0','Hampl', ...
                     'Pin','P0','n','alpha_inc','alpha1_inc','alpha2_inc','PortModeType', ...
                     'PortOrientation','TogglePowerFlowDirection','PeriodicType','Floquet_source', ...
                     'kFloquet','kFloquetx','kFloquety','kFloquetz','mOrder','nOrder','components'}, feature_id);
                if feature_is_periodic; facts.periodic{end+1} = fact_row; else; facts.excitation{end+1} = fact_row; end
            end
            physics_features(feature_node, component, physics, feature_id, effective_state, depth+1);
        end
    end

    function out_fact = output_fact(out_node, out_id, out_tag, out_kind, out_parent_dataset, out_parent_id)
        out_fact = basic(out_node, out_id); out_fact.tag = out_tag; out_fact.kind = out_kind;
        out_fact.parent = out_parent_id;
        [out_properties, out_fact.evaluated_properties] = properties(out_node, ...
            {'data','expr','unit','table','plotgroup','plot','innerinput','outerinput', ...
             'looplevelinput','solnum','outersolnum','xdata','xdataexpr','xdataunit','multiplecurves'}, out_id);
        out_fact.properties = out_properties;
        out_fact.dataset = []; out_fact.expressions = []; out_fact.units = []; out_fact.table = [];
        out_fact.dataset_binding = struct('status','unavailable');
        if isfield(out_properties, 'data')
            out_data = out_properties.data;
            if ischar(out_data) && ~isempty(out_data) && ~any(strcmp(out_data, {'parent','none','auto'}))
                out_fact.dataset = out_data;
                out_fact.dataset_binding = struct('status','explicit','source',out_id);
            elseif isequal(out_data, 'parent') && ischar(out_parent_dataset) && ~isempty(out_parent_dataset)
                out_fact.dataset = out_parent_dataset;
                out_fact.dataset_binding = struct('status','inherited','source',out_parent_id);
            end
        elseif any(strcmp(out_kind, {'plot','plot_modifier'})) && ischar(out_parent_dataset) && ~isempty(out_parent_dataset)
            % Plot modifiers without a dataset property operate on their parent.
            out_fact.dataset = out_parent_dataset;
            out_fact.dataset_binding = struct('status','inherited','source',out_parent_id);
        end
        if isfield(out_properties,'expr'); out_fact.expressions = out_properties.expr; end
        if isfield(out_properties,'unit'); out_fact.units = out_properties.unit; end
        if isfield(out_properties,'table'); out_fact.table = out_properties.table; end
    end

    function output_plots(plot_node, plot_tag, plot_id, plot_kind, plot_parent_dataset, plot_parent_id, plot_choice, plot_depth)
        if plot_depth > 4
            issue(plot_id, 'unavailable', 'Referenced plot nesting exceeds inspection depth.');
            return
        end
        plot_fact = output_fact(plot_node, plot_id, plot_tag, plot_kind, plot_parent_dataset, plot_parent_id);
        if ~any(strcmp(output_seen, plot_id))
            facts.outputs{end+1} = plot_fact;
            output_seen{end+1} = plot_id;
        end
        plot_children = read_tags(@() plot_node.feature.tags, [plot_id '/features']);
        if ischar(plot_choice) && ~isempty(plot_choice) && ~any(strcmp(plot_choice, {'all','none'}))
            if ~any(strcmp(plot_children, plot_choice))
                issue([plot_id '/' plot_choice], 'unavailable', 'Referenced plot is missing.');
                return
            end
            plot_children = {plot_choice};
        end
        for plot_index = 1:numel(plot_children)
            plot_child_tag = plot_children{plot_index};
            output_plots(plot_node.feature(plot_child_tag), plot_child_tag, [plot_id '/' plot_child_tag], ...
                'plot', plot_fact.dataset, plot_id, '', plot_depth+1);
        end
    end
end

function [solution, chain] = dataset_solution(datasets, tag, visited)
solution = []; chain = [visited, {tag}];
if any(strcmp(visited, tag)); return; end
for k = 1:numel(datasets)
    item = datasets{k};
    if ~strcmp(item.tag, tag); continue; end
    if ischar(item.solution) && ~isempty(item.solution) && ...
            ~any(strcmp(item.solution, {'none','auto'})) && ...
            ~isfield(item.properties,'data1') && ~isfield(item.properties,'data2')
        solution = item.solution;
    elseif ischar(item.source) && ~isempty(item.source) && ...
            ~isfield(item.properties,'data1') && ~isfield(item.properties,'data2')
        [solution, chain] = dataset_solution(datasets, item.source, chain);
    end
    return
end
end

function value = property_value(node, name)
% COMSOL documents typed getters; preserve matrices instead of flattening them.
kind = lower(char(node.getValueType(name)));
switch kind
    case 'boolean'; value = logical(node.getBoolean(name));
    case {'int','integer'}; value = double(node.getInt(name));
    case 'double'; value = double(node.getDouble(name));
    case {'intarray','integerarray'}; value = double(node.getIntArray(name));
    case 'doublearray'; value = double(node.getDoubleArray(name));
    case 'booleanarray'; value = logical(node.getBooleanArray(name));
    case {'doublematrix','doublerowmatrix'}; value = double(node.getDoubleMatrix(name));
    case 'stringmatrix'; value = cell(node.getStringMatrix(name));
    case 'stringarray'; value = strings_list(node.getStringArray(name));
    otherwise; value = char(node.getString(name));
end
value = plain(value);
% Scalar string arrays are conventional for several COMSOL reference properties.
if iscell(value) && numel(value) == 1 && ischar(value{1}); value = value{1}; end
end

function output = strings_list(value)
if ischar(value); output = {value}; elseif isstring(value); output = cellstr(value); else; output = cell(value); end
output = reshape(cellfun(@char, output, 'UniformOutput', false), 1, []);
end

function value = plain(value)
if isstring(value); value = cellstr(value);
elseif iscell(value)
    for k = 1:numel(value); value{k} = plain(value{k}); end
elseif isa(value, 'java.lang.String'); value = char(value);
elseif isjava(value)
    try; value = strings_list(value); catch; value = double(value); end
end
end
