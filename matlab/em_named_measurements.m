function values = em_named_measurements(model, measurements)
%EM_NAMED_MEASUREMENTS Evaluate trusted, explicitly bound package measurements.
% Never selects a default dataset, changes a study, or runs a solver.
% COMSOL 6.0 mphint2/mphmean/mphmax return units but do not document a unit
% input. Spatial quantities therefore require the declared native output unit.

values = cell(1, numel(measurements));
seen = {};
for k = 1:numel(measurements)
    if iscell(measurements); item = measurements{k}; else; item = measurements(k); end
    id = text_field(item, 'id');
    if any(strcmp(seen, id)); error('em:measurement_duplicate', 'Duplicate measurement id: %s', id); end
    seen{end+1} = id; %#ok<AGROW>
    expression = text_field(item, 'expression');
    method = text_field(item, 'method');
    study = text_field(item, 'study');
    solution = text_field(item, 'solution');
    dataset = text_field(item, 'dataset');
    unit = text_field(item, 'unit', true);
    solnum = solution_selector(item, 'solnum');
    outersolnum = solution_selector(item, 'outersolnum');
    binding = verify_binding(model, study, solution, dataset);
    selection = '';
    if isfield(item, 'selection'); selection = text_field(item, 'selection', true); end
    args = {'dataset', dataset, 'solnum', solnum, 'outersolnum', outersolnum};
    dimension = '';
    selection_info = struct();
    if strcmp(method, 'global')
        if ~isempty(selection); error('em:measurement_selection', 'Global measurement %s cannot have a selection.', id); end
        [value, actual_unit] = mphglobal(model, expression, args{:}, ...
            'unit', unit, 'complexout', 'on', 'matherr', 'on');
    else
        if ~any(strcmp(method, {'integrate', 'average', 'maximum'}))
            error('em:measurement_method', 'Unsupported measurement method: %s', method);
        end
        dimension = text_field(item, 'dimension');
        dimensions = {'line', 'surface', 'volume'};
        dim = find(strcmp(dimensions, dimension));
        if isempty(dim); error('em:measurement_dimension', 'Unknown entity dimension: %s', dimension); end
        if isempty(selection) || strcmp(selection, 'all')
            error('em:measurement_selection', 'Measurement %s needs an explicit named selection.', id);
        end
        selection_info = verify_selection(model, selection, dim);
        args = [args, {'selection', selection, 'squeeze', 'off'}]; %#ok<AGROW>
        switch method
            case 'integrate'; [value, actual_unit] = mphint2(model, expression, dimension, args{:});
            case 'average'; [value, actual_unit] = mphmean(model, expression, dimension, args{:});
            case 'maximum'; [value, actual_unit] = mphmax(model, expression, dimension, args{:});
        end
    end
    actual_unit = checked_unit(actual_unit, unit, id);
    require_finite(value, id);
    normalization = struct();
    output_unit = actual_unit;
    if isfield(item, 'normalization') && ~isempty(item.normalization) && ~isempty(fieldnames(item.normalization))
        norm_expression = text_field(item.normalization, 'expression');
        norm_unit = text_field(item.normalization, 'unit', true);
        [denominator, actual_norm_unit] = mphglobal(model, norm_expression, ...
            'dataset', dataset, 'solnum', solnum, 'outersolnum', outersolnum, ...
            'unit', norm_unit, 'complexout', 'on', 'matherr', 'on');
        actual_norm_unit = checked_unit(actual_norm_unit, norm_unit, [id ' normalization']);
        % This interface normalizes to a dimensionless ratio. Unit strings must
        % agree so that a declared normalization cannot silently change dimensions.
        checked_unit(actual_norm_unit, actual_unit, [id ' normalization numerator']);
        require_finite(denominator, [id ' normalization']);
        if any(denominator(:) == 0)
            error('em:measurement_normalization', 'Zero normalization for %s.', id);
        end
        if ~isscalar(denominator) && ~isequal(size(denominator), size(value))
            if isvector(denominator) && isvector(value) && numel(denominator) == numel(value)
                denominator = reshape(denominator, size(value));
            else
                error('em:measurement_normalization', 'Normalization shape does not match %s.', id);
            end
        end
        value = value ./ denominator;
        require_finite(value, id);
        normalization = struct('expression', norm_expression, 'unit', actual_norm_unit, ...
            'value_real', real(denominator), 'value_imag', imag(denominator), 'size', size(denominator));
        output_unit = '1';
    end
    binding.solnum = solnum;
    binding.outersolnum = outersolnum;
    binding.selection = selection;
    binding.selection_facts = selection_info;
    binding.dimension = dimension;
    values{k} = struct('id', id, 'method', method, 'expression', expression, ...
        'value_real', real(value), 'value_imag', imag(value), 'size', size(value), ...
        'unit', output_unit, 'numerator_unit', actual_unit, ...
        'normalization', normalization, 'binding', binding);
end
end

function binding = verify_binding(model, study, solution, dataset)
if ~any(strcmp(tags(model.study.tags), study))
    error('em:measurement_binding', 'Unknown study: %s', study);
end
if ~any(strcmp(tags(model.sol.tags), solution))
    error('em:measurement_binding', 'Unknown solution: %s', solution);
end
available = tags(model.result.dataset.tags);
chain = {};
current = dataset;
while true
    if ~any(strcmp(available, current)) || any(strcmp(chain, current))
        error('em:measurement_binding', 'Missing or cyclic dataset binding at %s.', current);
    end
    chain{end+1} = current; %#ok<AGROW>
    node = model.result.dataset(current);
    properties = tags(node.properties());
    if any(ismember({'data1', 'data2'}, properties))
        error('em:measurement_binding', 'Dataset %s has multiple possible sources.', current);
    end
    if any(strcmp(properties, 'solution'))
        actual_solution = char(node.getString('solution'));
        if ~isempty(actual_solution) && ~any(strcmp(actual_solution, {'none','auto'})); break; end
    end
    if ~any(strcmp(properties, 'data'))
        error('em:measurement_binding', 'Dataset %s has no unambiguous single solution source.', current);
    end
    current = char(node.getString('data'));
end
if ~strcmp(actual_solution, solution)
    error('em:measurement_binding', 'Dataset %s uses %s, not declared solution %s.', dataset, actual_solution, solution);
end
if logical(model.sol(solution).isEmpty())
    error('em:measurement_empty_solution', 'Solution %s is empty.', solution);
end
info = mphsolinfo(model, 'soltag', solution, 'NU', 'on');
if ~isfield(info, 'study') || ~strcmp(char(info.study), study)
    error('em:measurement_binding', 'Solution %s does not establish declared study %s.', solution, study);
end
binding = struct('study', study, 'solution', solution, 'dataset', dataset, ...
    'dataset_chain', {chain}, 'solution_type', char(info.soltype));
% These values belong to the saved solution, not current model parameters.
binding.solution_samples = struct();
sample_fields = {'solpar','solvals','sizesolvals','paramsweepnames','paramsweepvals','sizes','NUsol'};
for k = 1:numel(sample_fields)
    field = sample_fields{k};
    if isfield(info, field); binding.solution_samples.(field) = info.(field); end
end
end

function result = verify_selection(model, name, expected_dimension)
matches = {};
components = tags(model.component.tags);
for k = 1:numel(components)
    component = components{k};
    names = tags(model.component(component).selection.tags);
    for j = 1:numel(names)
        tag = names{j};
        if strcmp(name, tag) || strcmp(name, [component '_' tag])
            info = mphgetselection(model.component(component).selection(tag));
            matches{end+1} = selection_result(info, component, tag); %#ok<AGROW>
        end
    end
end
% Global selections are possible without a component. Component matches take
% precedence because the legacy model.selection API also aliases these nodes.
if isempty(matches)
    names = tags(model.selection.tags);
    if any(strcmp(names, name))
        matches = {selection_result(mphgetselection(model.selection(name)), '', name)};
    end
end
if numel(matches) ~= 1
    error('em:measurement_selection', 'Named selection %s is missing or ambiguous.', name);
end
result = matches{1};
if result.dimension ~= expected_dimension || isempty(result.entities)
    error('em:measurement_selection', 'Selection %s is empty or has dimension %g; expected %g.', name, result.dimension, expected_dimension);
end
end

function result = selection_result(info, component, tag)
if ~isscalar(info.dimension) || iscell(info.entities)
    error('em:measurement_selection', 'Selection %s spans multiple entity dimensions.', tag);
end
result = struct('component', component, 'tag', tag, ...
    'dimension', info.dimension, 'geometry', char(info.geom), ...
    'entities', reshape(double(info.entities), 1, []), 'count', numel(info.entities));
end

function value = solution_selector(item, name)
if ~isfield(item, name); error('em:measurement_selector', 'Missing explicit %s.', name); end
value = item.(name);
if (ischar(value) || (isstring(value) && isscalar(value))) && strcmp(char(value), 'all')
    value = 'all';
elseif ~(isnumeric(value) && isscalar(value) && isfinite(value) && value > 0 && value == fix(value))
    error('em:measurement_selector', '%s must be all or a positive integer.', name);
end
end

function unit = checked_unit(actual, expected, id)
if iscell(actual)
    if numel(actual) ~= 1; error('em:measurement_unit_mismatch', 'Multiple returned units for %s.', id); end
    actual = actual{1};
end
unit = strtrim(char(actual));
expected = strtrim(char(expected));
if isempty(unit); unit = '1'; end
if isempty(expected); expected = '1'; end
if ~strcmp(unit, expected)
    error('em:measurement_unit_mismatch', 'Unit mismatch for %s: requested %s, actual %s. Spatial measurements require the native returned unit.', id, expected, unit);
end
end

function require_finite(value, id)
if ~isnumeric(value) || isempty(value) || any(~isfinite(value(:)))
    error('em:measurement_nonfinite', 'Empty or nonfinite measurement: %s.', id);
end
end

function value = text_field(item, name, allow_empty)
if nargin < 3; allow_empty = false; end
if ~isstruct(item) || ~isscalar(item) || ~isfield(item, name)
    error('em:measurement_definition', 'Missing measurement field: %s.', name);
end
value = item.(name);
if ~(ischar(value) && (isrow(value) || isempty(value))) && ~(isstring(value) && isscalar(value))
    error('em:measurement_definition', '%s must be text.', name);
end
value = char(value);
if ~allow_empty && isempty(strtrim(value)); error('em:measurement_definition', '%s cannot be empty.', name); end
end

function out = tags(value)
if ischar(value); out = {value}; elseif isstring(value); out = cellstr(value); else; out = cell(value); end
out = cellfun(@char, out, 'UniformOutput', false);
end
