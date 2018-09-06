import {InputWidget, InputWidgetView} from 'models/widgets/input_widget'
import {createElement, div, empty} from 'core/dom'
import * as p from 'core/properties'


const ajax = axios.create({
    headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET POST OPTIONS'
    }
});


class VueMultiselectView extends InputWidgetView {
    initialize(options) {
        super.initialize(options);
        empty(this.el);
        this.el.appendChild(this.template());
        this.$bus = new Vue();
        this.connect(this.model.properties.selectedOptions.change, () => this.$bus.$emit('update-value', this.model.selectedOptions));
        this.connect(this.model.properties.options.change, () => this.$bus.$emit('update-options', this.model.options));
        this.connect(this.model.properties.modelName.change, () => this.$bus.$emit('update-model-name', this.model.modelName));
        this.render();
    }

    template() {
        return div();
    }

    updateSelectedOptions(selectedOptions) {
        this.model.selectedOptions = selectedOptions;
        this.model.properties.selectedOptions.change.emit();
    }

    updateOptions(options) {
        this.model.options = options;
        this.model.properties.options.change.emit();
    }

    updateModelName(modelName) {
        this.model.modelName = modelName;
        this.model.properties.modelName.emit();
    }

    render() {
        super.render();
        const opts = {
            selectedOptions: this.model.selectedOptions,
            options: this.model.options,
            modelName: this.model.modelName,
            isLoading: false
        };
        let self = this;
        const component = new Vue({
            components: {
                Multiselect: VueMultiselect.default
            },
            created() {
                self.$bus.$on('update-value', this.handleUpdateSelectedOptions);
                self.$bus.$on('update-options', this.handleUpdateOptions);
                self.$bus.$on('update-model-name', this.handleUpdateModelName);
            },
            template: `<multiselect 
                @input="sendSelectedOptionsUpdate" 
                :value="selectedOptions"
                track-by="value"
                label="label"
                :options="options"
                :multiple="true"
                :loading="isLoading"
                :searchable="true"
                :internal-search="false"
                :clear-on-select="false"
                :close-on-select="false"
                @search-change="asyncFind">    
            </multiselect>`,
            data() {
                return opts
            },
            methods: {
                sendSelectedOptionsUpdate: function(selectedOptions) {
                    self.updateSelectedOptions(selectedOptions);
                },

                sendOptionsUpdate: function(options) {
                    self.updateOptions(options);
                },

                handleUpdateSelectedOptions: function(selectedOptions) {
                    this.selectedOptions = selectedOptions;
                },

                handleUpdateOptions: function(options) {
                    this.options = options;
                },

                handleUpdateModelName: function(modelName) {
                    this.modelName = modelName;
                },

                asyncFind: debounce(async function(q) {
                    if (q) {
                        this.isLoading = true;
                        const response = await ajax.get(`/autocomplete/${this.modelName}?q=${q}`);
                        this.sendOptionsUpdate(response.data);
                        this.isLoading = false;
                    }
                }, 500)
            }
        });
        this.$component = component;
        this.$component.$mount(this.el);
    }
}

export class VueMultiselectWidget extends InputWidget {

    constructor(attrs) {
        super(attrs)
    }

    static initClass() {
        this.prototype.type = 'VueMultiselectWidget';
        this.prototype.default_view = VueMultiselectView;

        this.define({
            selectedOptions: [p.Array],
            options: [p.Array, []],
            modelName: [p.String, 'platform']
        });
    }
}

VueMultiselectWidget.initClass();


